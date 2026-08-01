import os
import json
from threading import Thread
from datetime import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
    ConversationHandler,
)
from flask import Flask

# --- مراحل المحادثات (Conversation States) ---
# إضافة وارد
INCOME_WAITING_FOR_NAME, INCOME_WAITING_FOR_AMOUNT, INCOME_WAITING_FOR_TYPE = range(3)

# إضافة دين
ADD_WAITING_FOR_NAME, ADD_WAITING_FOR_NEW_NAME, ADD_WAITING_FOR_AMOUNT, ADD_WAITING_FOR_TYPE = range(3, 7)

# سداد دين
PAY_WAITING_FOR_NAME, PAY_WAITING_FOR_AMOUNT, PAY_WAITING_FOR_FROM_WALLET, PAY_WAITING_FOR_TO_WALLET = range(7, 11)

# إضافة مصروف
EXPENSE_WAITING_FOR_PERSON, EXPENSE_WAITING_FOR_AMOUNT, EXPENSE_WAITING_FOR_TYPE = range(11, 14)

# --- 0. سيرفر وهمي لتشغيل البوت على Render مجاناً ---
web_app = Flask('')

@web_app.route('/')
def home():
    return "Bot is running online!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    web_app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_flask)
    t.start()

# --- 1. الإتصال بجوجل شيت ---
def get_sheets():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    
    if "GOOGLE_CREDENTIALS" in os.environ:
        creds_dict = json.loads(os.environ["GOOGLE_CREDENTIALS"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    else:
        creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
        
    client = gspread.authorize(creds)
    spreadsheet = client.open("كفي الشرفا")
    
    total_debts_sheet = spreadsheet.worksheet("الديون الإجمالية")
    
    try:
        debt_log_sheet = spreadsheet.worksheet("سجل الديون")
    except Exception:
        debt_log_sheet = total_debts_sheet

    try:
        pay_log_sheet = spreadsheet.worksheet("سجل السداد")
    except Exception:
        pay_log_sheet = total_debts_sheet

    try:
        summary_sheet = spreadsheet.worksheet("الإجمالي")
    except Exception:
        summary_sheet = total_debts_sheet

    try:
        expenses_sheet = spreadsheet.worksheet("المصروفات")
    except Exception:
        expenses_sheet = total_debts_sheet

    try:
        income_sheet = spreadsheet.worksheet("الوارد")
    except Exception:
        income_sheet = total_debts_sheet
        
    return total_debts_sheet, debt_log_sheet, pay_log_sheet, summary_sheet, expenses_sheet, income_sheet

# دالة مساعدة لتحديث قيمة خلايا الإجمالي
def update_summary_cell(sheet, cell_address, amount_delta):
    cell_val = sheet.acell(cell_address).value
    try:
        current_val = float(str(cell_val).replace(',', '').strip()) if cell_val else 0.0
    except ValueError:
        current_val = 0.0
    new_val = current_val + amount_delta
    sheet.update_acell(cell_address, new_val)
    return new_val

# --- 2. لوحات الأزرار ---

def main_menu_keyboard():
    keyboard = [
        [KeyboardButton("📥 إضافة وارد")],
        [KeyboardButton("➕ إضافة دين")],
        [KeyboardButton("💳 سداد دين")],
        [KeyboardButton("💸 إضافة مصروف")],
        [KeyboardButton("📊 الإجمالي")] # الزر الجديد المضاف
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def person_keyboard():
    keyboard = [
        [KeyboardButton("عبود"), KeyboardButton("طارق")],
        [KeyboardButton("🔙 رجوع")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def back_only_keyboard():
    keyboard = [
        [KeyboardButton("🔙 رجوع")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def build_names_keyboard(include_add_button=False):
    error_msg = None
    names = []
    try:
        total_debts_sheet, _, _, _, _, _ = get_sheets()
        col_values = total_debts_sheet.col_values(1)
        names = [val.strip() for val in col_values if val.strip() and val.strip() not in ["الاسم", "الإسم"]]
    except Exception as e:
        error_msg = str(e)

    keyboard = []
    for name in names:
        keyboard.append([KeyboardButton(f"👤 {name}")])
        
    if include_add_button:
        keyboard.append([KeyboardButton("➕ إضافة إسم")])
        
    keyboard.append([KeyboardButton("🔙 رجوع")])
    
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True), error_msg

# --- 3. الأوامر العامة ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "مرحباً بك! اختر العملية المطلوبة من الأسفل:",
        reply_markup=main_menu_keyboard()
    )

async def cancel_to_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("تم العودة للقائمة الرئيسية.", reply_markup=main_menu_keyboard())
    return ConversationHandler.END

# --- دالة عرض الإجمالي الجديد ---
async def show_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ جاري جلب بيانات الإجمالي...")
    try:
        _, _, _, summary_sheet, _, _ = get_sheets()
        
        # جلب النطاق من A1 إلى B5 دفعة واحدة لتقليل طلبات الـ API
        cell_range = summary_sheet.get('A1:B5')
        
        response_text = "📊 **ملخص صفحة الإجمالي:**\n\n"
        
        for i in range(5):
            row = cell_range[i] if i < len(cell_range) else []
            val_a = row[0] if len(row) > 0 else ""
            val_b = row[1] if len(row) > 1 else ""
            
            response_text += f"{val_a} : {val_b}\n"

        await update.message.reply_text(
            response_text,
            parse_mode='Markdown',
            reply_markup=main_menu_keyboard()
        )
    except Exception as e:
        await update.message.reply_text(f"❌ حدث خطأ أثناء جلب البيانات: {e}", reply_markup=main_menu_keyboard())

# --- 4. محادثة [📥 إضافة وارد] ---

async def start_add_income(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📥 (إضافة وارد) أدخل **الاسم**:",
        parse_mode='Markdown',
        reply_markup=back_only_keyboard()
    )
    return INCOME_WAITING_FOR_NAME

async def income_process_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    
    if name == "🔙 رجوع":
        return await cancel_to_main(update, context)

    context.user_data['income_name'] = name
    
    await update.message.reply_text(
        f"👤 الاسم: **{name}**\n\n💵 أدخل **المبلغ**:",
        parse_mode='Markdown',
        reply_markup=back_only_keyboard()
    )
    return INCOME_WAITING_FOR_AMOUNT

async def income_process_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    
    if text == "🔙 رجوع":
        return await start_add_income(update, context)

    try:
        amount = float(text)
        context.user_data['income_amount'] = amount
    except ValueError:
        await update.message.reply_text("⚠️ يرجى إدخال رقم صحيح للمبلغ:", reply_markup=back_only_keyboard())
        return INCOME_WAITING_FOR_AMOUNT

    await update.message.reply_text(
        "📝 أدخل **نوع الوارد** (الوصف):\n\nمثال: `مبيعات شفت صباحي`",
        parse_mode='Markdown',
        reply_markup=back_only_keyboard()
    )
    return INCOME_WAITING_FOR_TYPE

async def income_save_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    income_type = update.message.text.strip()
    
    if income_type == "🔙 رجوع":
        name = context.user_data.get('income_name', '')
        await update.message.reply_text(
            f"👤 الاسم: **{name}**\n\n💵 أدخل **المبلغ**:",
            parse_mode='Markdown',
            reply_markup=back_only_keyboard()
        )
        return INCOME_WAITING_FOR_AMOUNT

    name = context.user_data.get('income_name')
    amount = context.user_data.get('income_amount')
    current_date = datetime.now().strftime("%Y-%m-%d %H:%M")

    await update.message.reply_text("⏳ جاري حفظ الوارد وتحديث الإجمالي...")

    try:
        _, _, _, summary_sheet, _, income_sheet = get_sheets()
        
        income_sheet.append_row([name, amount, income_type, current_date])
        update_summary_cell(summary_sheet, 'B5', amount)

        await update.message.reply_text(
            f"✅ **تم إضافة الوارد بنجاح!**\n\n"
            f"👤 **الاسم:** {name}\n"
            f"💵 **المبلغ:** {amount}\n"
            f"📝 **النوع:** {income_type}\n"
            f"📅 **التاريخ:** {current_date}",
            parse_mode='Markdown',
            reply_markup=main_menu_keyboard()
        )
    except Exception as e:
        await update.message.reply_text(f"❌ حدث خطأ أثناء الحفظ: {e}", reply_markup=main_menu_keyboard())

    context.user_data.clear()
    return ConversationHandler.END

# --- 5. محادثة [➕ إضافة دين] ---

async def start_add_debt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    names_markup, err = build_names_keyboard(include_add_button=True)
    if err:
        await update.message.reply_text(f"❌ حدث خطأ في الاتصال بجوجل شيت:\n`{err}`", parse_mode='Markdown')
        return ConversationHandler.END
    
    await update.message.reply_text("📋 (إضافة دين) اختر اسم الزبون من القائمة أو اضغط على إضافة إسم:", reply_markup=names_markup)
    return ADD_WAITING_FOR_NAME

async def add_process_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    
    if text == "🔙 رجوع":
        return await cancel_to_main(update, context)

    if text == "➕ إضافة إسم":
        await update.message.reply_text("✍️ أدخل **اسم الزبون الجديد** لإنشائه في الشيت:", parse_mode='Markdown', reply_markup=back_only_keyboard())
        return ADD_WAITING_FOR_NEW_NAME

    selected_name = text.replace("👤 ", "").strip()
    context.user_data['selected_name'] = selected_name
    
    await update.message.reply_text(
        f"👤 الزبون: **{selected_name}**\n\n💵 أدخل **مبلغ الدين**:",
        parse_mode='Markdown',
        reply_markup=back_only_keyboard()
    )
    return ADD_WAITING_FOR_AMOUNT

async def add_save_new_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_name = update.message.text.strip()
    
    if new_name == "🔙 رجوع":
        return await start_add_debt(update, context)
        
    if not new_name:
        await update.message.reply_text("⚠️ يرجى إدخال اسم صحيح:", reply_markup=back_only_keyboard())
        return ADD_WAITING_FOR_NEW_NAME

    await update.message.reply_text("⏳ جاري إضافة الزبون الجديد في صفحة الديون الإجمالية...")
    
    try:
        total_sheet, _, _, _, _, _ = get_sheets()
        total_sheet.append_row([new_name, 0])
        
        await update.message.reply_text(f"✅ تم إضافة الزبون **{new_name}** بنجاح!", parse_mode='Markdown')
        
        return await start_add_debt(update, context)
    except Exception as e:
        await update.message.reply_text(f"❌ حدث خطأ أثناء إضافة الاسم: {e}", reply_markup=main_menu_keyboard())
        return ConversationHandler.END

async def add_process_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    
    if text == "🔙 رجوع":
        return await start_add_debt(update, context)

    try:
        amount = float(text)
        context.user_data['amount'] = amount
    except ValueError:
        await update.message.reply_text("⚠️ يرجى إدخال رقم صحيح للمبلغ:", reply_markup=back_only_keyboard())
        return ADD_WAITING_FOR_AMOUNT

    await update.message.reply_text(
        "📝 أدخل **نوع الدين** (الوصف):\n\nمثال: `5 قهوة + 2 بلياردو`",
        parse_mode='Markdown',
        reply_markup=back_only_keyboard()
    )
    return ADD_WAITING_FOR_TYPE

async def add_save_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    item_type = update.message.text.strip()
    
    if item_type == "🔙 رجوع":
        name = context.user_data.get('selected_name', '')
        await update.message.reply_text(
            f"👤 الزبون: **{name}**\n\n💵 أدخل **مبلغ الدين**:",
            parse_mode='Markdown',
            reply_markup=back_only_keyboard()
        )
        return ADD_WAITING_FOR_AMOUNT

    name = context.user_data.get('selected_name')
    amount = context.user_data.get('amount')
    current_date = datetime.now().strftime("%Y-%m-%d %H:%M")

    await update.message.reply_text("⏳ جاري حفظ البيانات في جوجل شيت...")

    try:
        total_sheet, debt_log_sheet, _, summary_sheet, _, _ = get_sheets()
        
        debt_log_sheet.append_row([name, amount, item_type, current_date])

        col_values = [v.lower() for v in total_sheet.col_values(1)]
        search_name = name.lower()
        
        if search_name in col_values:
            row_index = col_values.index(search_name) + 1
            cell_val = total_sheet.cell(row_index, 2).value
            current_amount = float(cell_val) if cell_val else 0.0
            new_amount = current_amount + amount
            total_sheet.update_cell(row_index, 2, new_amount)
        else:
            new_amount = amount
            total_sheet.append_row([name, new_amount])

        update_summary_cell(summary_sheet, 'B1', amount)

        await update.message.reply_text(
            f"✅ **تم إضافة الدين بنجاح!**\n\n"
            f"👤 **الاسم:** {name}\n"
            f"💵 **المبلغ:** {amount}\n"
            f"📝 **النوع:** {item_type}\n"
            f"📅 **التاريخ:** {current_date}\n\n"
            f"💰 **إجمالي الدين الحالي للزبون:** {new_amount}",
            parse_mode='Markdown',
            reply_markup=main_menu_keyboard()
        )
    except Exception as e:
        await update.message.reply_text(f"❌ حدث خطأ أثناء الحفظ: {e}", reply_markup=main_menu_keyboard())

    context.user_data.clear()
    return ConversationHandler.END

# --- 6. محادثة [💳 سداد دين] ---

async def start_pay_debt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    names_markup, err = build_names_keyboard(include_add_button=False)
    if err:
        await update.message.reply_text(f"❌ حدث خطأ في الاتصال بجوجل شيت:\n`{err}`", parse_mode='Markdown')
        return ConversationHandler.END
    
    await update.message.reply_text("💳 (سداد دين) اختر اسم الزبون من القائمة:", reply_markup=names_markup)
    return PAY_WAITING_FOR_NAME

async def pay_process_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    
    if text == "🔙 رجوع":
        return await cancel_to_main(update, context)
        
    selected_name = text.replace("👤 ", "").strip()
    context.user_data['selected_name'] = selected_name
    
    await update.message.reply_text(
        f"👤 الزبون: **{selected_name}**\n\n💵 أدخل **مبلغ السداد**:",
        parse_mode='Markdown',
        reply_markup=back_only_keyboard()
    )
    return PAY_WAITING_FOR_AMOUNT

async def pay_process_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    
    if text == "🔙 رجوع":
        return await start_pay_debt(update, context)

    try:
        amount = float(text)
        context.user_data['amount'] = amount
    except ValueError:
        await update.message.reply_text("⚠️ يرجى إدخال رقم صحيح للمبلغ:", reply_markup=back_only_keyboard())
        return PAY_WAITING_FOR_AMOUNT

    await update.message.reply_text(
        "✍️ **تم التحويل من محفظة؟**\n(أدخل الاسم كتابةً):",
        parse_mode='Markdown',
        reply_markup=back_only_keyboard()
    )
    return PAY_WAITING_FOR_FROM_WALLET

async def pay_process_from_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from_wallet = update.message.text.strip()
    
    if from_wallet == "🔙 رجوع":
        name = context.user_data.get('selected_name', '')
        await update.message.reply_text(
            f"👤 الزبون: **{name}**\n\n💵 أدخل **مبلغ السداد**:",
            parse_mode='Markdown',
            reply_markup=back_only_keyboard()
        )
        return PAY_WAITING_FOR_AMOUNT

    context.user_data['from_wallet'] = from_wallet

    await update.message.reply_text(
        "✍️ **تم التحويل إلى محفظة؟**\n(أدخل الاسم كتابةً):",
        parse_mode='Markdown',
        reply_markup=back_only_keyboard()
    )
    return PAY_WAITING_FOR_TO_WALLET

async def pay_save_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    to_wallet = update.message.text.strip()
    
    if to_wallet == "🔙 رجوع":
        await update.message.reply_text(
            "✍️ **تم التحويل من محفظة؟**\n(أدخل الاسم كتابةً):",
            parse_mode='Markdown',
            reply_markup=back_only_keyboard()
        )
        return PAY_WAITING_FOR_FROM_WALLET

    name = context.user_data.get('selected_name')
    amount = context.user_data.get('amount')
    from_wallet = context.user_data.get('from_wallet')
    current_date = datetime.now().strftime("%Y-%m-%d %H:%M")

    await update.message.reply_text("⏳ جاري تسجيل عملية السداد...")

    try:
        total_sheet, _, pay_log_sheet, summary_sheet, _, _ = get_sheets()
        
        pay_log_sheet.append_row([name, amount, from_wallet, to_wallet, current_date])

        col_values = [v.lower() for v in total_sheet.col_values(1)]
        search_name = name.lower()
        
        if search_name in col_values:
            row_index = col_values.index(search_name) + 1
            cell_val = total_sheet.cell(row_index, 2).value
            current_amount = float(cell_val) if cell_val else 0.0
            new_amount = current_amount - amount
            
            if new_amount <= 0:
                total_sheet.update_cell(row_index, 2, 0)
                msg_total = "🎉 تم تسديد كامل الدين!"
            else:
                total_sheet.update_cell(row_index, 2, new_amount)
                msg_total = f"💰 المتبقي عليه: **{new_amount}**"
        else:
            msg_total = "⚠️ الاسم غير مسجل في الديون الإجمالية."

        update_summary_cell(summary_sheet, 'B1', -amount)

        await update.message.reply_text(
            f"✅ **تم تسجيل السداد بنجاح!**\n\n"
            f"👤 **الاسم:** {name}\n"
            f"💵 **المبلغ المسدد:** {amount}\n"
            f"📤 **من محفظة:** {from_wallet}\n"
            f"📥 **إلى محفظة:** {to_wallet}\n"
            f"📅 **التاريخ:** {current_date}\n\n"
            f"{msg_total}",
            parse_mode='Markdown',
            reply_markup=main_menu_keyboard()
        )
    except Exception as e:
        await update.message.reply_text(f"❌ حدث خطأ أثناء التسجيل: {e}", reply_markup=main_menu_keyboard())

    context.user_data.clear()
    return ConversationHandler.END

# --- 7. محادثة [💸 إضافة مصروف] ---

async def start_add_expense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💸 **مين دفع المصروف؟**",
        reply_markup=person_keyboard(),
        parse_mode='Markdown'
    )
    return EXPENSE_WAITING_FOR_PERSON

async def expense_process_person(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    
    if text == "🔙 رجوع":
        return await cancel_to_main(update, context)

    if text not in ["عبود", "طارق"]:
        await update.message.reply_text("⚠️ يرجى اختيار اسم من الأزرار المتاحة (عبود أو طارق):", reply_markup=person_keyboard())
        return EXPENSE_WAITING_FOR_PERSON

    context.user_data['expense_person'] = text
    
    await update.message.reply_text(
        f"👤 الدَافع: **{text}**\n\n💵 كم **مبلغ المصروف**؟",
        parse_mode='Markdown',
        reply_markup=back_only_keyboard()
    )
    return EXPENSE_WAITING_FOR_AMOUNT

async def expense_process_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    
    if text == "🔙 رجوع":
        return await start_add_expense(update, context)

    try:
        amount = float(text)
        context.user_data['expense_amount'] = amount
    except ValueError:
        await update.message.reply_text("⚠️ يرجى إدخال رقم صحيح للمبلغ:", reply_markup=back_only_keyboard())
        return EXPENSE_WAITING_FOR_AMOUNT

    await update.message.reply_text(
        "📝 أدخل **نوع المصروف** (الوصف):\n\nمثال: `كرتونة أندومي`",
        parse_mode='Markdown',
        reply_markup=back_only_keyboard()
    )
    return EXPENSE_WAITING_FOR_TYPE

async def expense_save_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    expense_type = update.message.text.strip()
    
    if expense_type == "🔙 رجوع":
        person = context.user_data.get('expense_person', '')
        await update.message.reply_text(
            f"👤 الدَافع: **{person}**\n\n💵 كم **مبلغ المصروف**؟",
            parse_mode='Markdown',
            reply_markup=back_only_keyboard()
        )
        return EXPENSE_WAITING_FOR_AMOUNT

    person = context.user_data.get('expense_person')
    amount = context.user_data.get('expense_amount')
    current_date = datetime.now().strftime("%Y-%m-%d %H:%M")

    await update.message.reply_text("⏳ جاري حفظ المصروف في جوجل شيت...")

    try:
        _, _, _, summary_sheet, expenses_sheet, _ = get_sheets()
        
        expenses_sheet.append_row([person, amount, expense_type, current_date])

        if person == "عبود":
            update_summary_cell(summary_sheet, 'B2', amount)
        elif person == "طارق":
            update_summary_cell(summary_sheet, 'B3', amount)

        update_summary_cell(summary_sheet, 'B4', amount)

        await update.message.reply_text(
            f"✅ **تم إضافة المصروف بنجاح!**\n\n"
            f"👤 **الاسم:** {person}\n"
            f"💵 **المبلغ:** {amount}\n"
            f"📝 **النوع:** {expense_type}\n"
            f"📅 **التاريخ:** {current_date}",
            parse_mode='Markdown',
            reply_markup=main_menu_keyboard()
        )
    except Exception as e:
        await update.message.reply_text(f"❌ حدث خطأ أثناء تسجيل المصروف: {e}", reply_markup=main_menu_keyboard())

    context.user_data.clear()
    return ConversationHandler.END

# --- 8. التشغيل الرئيسي ---
if __name__ == '__main__':
    keep_alive()
    
    TOKEN = "8718346069:AAHWbPMhPLiOMOtM_zGUZZjWg133U5EtyE0"
    
    app = ApplicationBuilder().token(TOKEN).build()
    
    # محادثة إضافة وارد
    income_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📥 إضافة وارد$"), start_add_income)],
        states={
            INCOME_WAITING_FOR_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, income_process_name)],
            INCOME_WAITING_FOR_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, income_process_amount)],
            INCOME_WAITING_FOR_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, income_save_final)],
        },
        fallbacks=[CommandHandler("start", start)]
    )

    # محادثة إضافة الدين
    add_debt_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^➕ إضافة دين$"), start_add_debt)],
        states={
            ADD_WAITING_FOR_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_process_name)],
            ADD_WAITING_FOR_NEW_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_save_new_name)],
            ADD_WAITING_FOR_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_process_amount)],
            ADD_WAITING_FOR_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_save_final)],
        },
        fallbacks=[CommandHandler("start", start)]
    )

    # محادثة سداد الدين
    pay_debt_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^💳 سداد دين$"), start_pay_debt)],
        states={
            PAY_WAITING_FOR_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, pay_process_name)],
            PAY_WAITING_FOR_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, pay_process_amount)],
            PAY_WAITING_FOR_FROM_WALLET: [MessageHandler(filters.TEXT & ~filters.COMMAND, pay_process_from_wallet)],
            PAY_WAITING_FOR_TO_WALLET: [MessageHandler(filters.TEXT & ~filters.COMMAND, pay_save_final)],
        },
        fallbacks=[CommandHandler("start", start)]
    )

    # محادثة إضافة مصروف
    expense_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^💸 إضافة مصروف$"), start_add_expense)],
        states={
            EXPENSE_WAITING_FOR_PERSON: [MessageHandler(filters.TEXT & ~filters.COMMAND, expense_process_person)],
            EXPENSE_WAITING_FOR_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, expense_process_amount)],
            EXPENSE_WAITING_FOR_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, expense_save_final)],
        },
        fallbacks=[CommandHandler("start", start)]
    )
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(income_conv)
    app.add_handler(add_debt_conv)
    app.add_handler(pay_debt_conv)
    app.add_handler(expense_conv)
    
    # معالج الضغط على زر "الإجمالي"
    app.add_handler(MessageHandler(filters.Regex("^📊 الإجمالي$"), show_summary))
    
    print("البوت يعمل الآن...")
    app.run_polling()
