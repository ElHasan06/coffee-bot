import os
import json
from threading import Thread
from datetime import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
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
# إضافة دين
ADD_WAITING_FOR_NAME, ADD_WAITING_FOR_AMOUNT, ADD_WAITING_FOR_TYPE = range(3)

# سداد دين
PAY_WAITING_FOR_NAME, PAY_WAITING_FOR_AMOUNT, PAY_WAITING_FOR_WALLET = range(3, 6)

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

# --- 1. الإتصال بجوجل شيت مع ربط الصفحات المحددة ---
def get_sheets():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    
    if "GOOGLE_CREDENTIALS" in os.environ:
        creds_dict = json.loads(os.environ["GOOGLE_CREDENTIALS"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    else:
        creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
        
    client = gspread.authorize(creds)
    spreadsheet = client.open("كفي الشرفا")
    
    # ربط الصفحات حسب الأسماء الجديدة تماماً
    total_debts_sheet = spreadsheet.worksheet("الديون الإجمالية")
    
    try:
        debt_log_sheet = spreadsheet.worksheet("سجل الديون")
    except Exception:
        debt_log_sheet = total_debts_sheet

    try:
        pay_log_sheet = spreadsheet.worksheet("سجل السداد")
    except Exception:
        pay_log_sheet = total_debts_sheet
        
    return total_debts_sheet, debt_log_sheet, pay_log_sheet

# --- 2. لوحات الأزرار ---

def main_menu_keyboard():
    keyboard = [
        [KeyboardButton("➕ إضافة دين")],
        [KeyboardButton("💳 سداد دين")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# أزرار المحافظ بعرض الشاشة
def wallet_keyboard():
    keyboard = [
        [KeyboardButton("عبود محفظة")],
        [KeyboardButton("عبود جوال بي")],
        [KeyboardButton("طارق محفظة")],
        [KeyboardButton("طارق جوال بي")],
        [KeyboardButton("❌ إلغاء العملية")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def build_names_keyboard():
    error_msg = None
    try:
        total_debts_sheet, _, _ = get_sheets()
        col_values = total_debts_sheet.col_values(1)
        names = [val.strip() for val in col_values if val.strip() and val.strip() not in ["الاسم", "الإسم"]]
    except Exception as e:
        names = []
        error_msg = str(e)

    keyboard = []
    for name in names:
        keyboard.append([KeyboardButton(f"👤 {name}")])
        
    keyboard.append([KeyboardButton("❌ إلغاء العملية")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True), error_msg, len(names)

# --- 3. الأوامر العامة ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "مرحباً بك! اختر العملية المطلوبة من الأسفل:",
        reply_markup=main_menu_keyboard()
    )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("تم إلغاء العملية.", reply_markup=main_menu_keyboard())
    return ConversationHandler.END

# --- 4. محادثة [➕ إضافة دين] ---

async def start_add_debt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    names_markup, err, count = build_names_keyboard()
    if err:
        await update.message.reply_text(f"❌ حدث خطأ في الاتصال بجوجل شيت:\n`{err}`", parse_mode='Markdown')
        return ConversationHandler.END
    elif count == 0:
        await update.message.reply_text("⚠️ لم يتم العثور على أي أسماء في صفحة الديون الإجمالية!", reply_markup=main_menu_keyboard())
        return ConversationHandler.END
    
    await update.message.reply_text("📋 (إضافة دين) اختر اسم الزبون من القائمة:", reply_markup=names_markup)
    return ADD_WAITING_FOR_NAME

async def add_process_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "❌ إلغاء العملية":
        return await cancel(update, context)
        
    selected_name = text.replace("👤 ", "").strip()
    context.user_data['selected_name'] = selected_name
    
    await update.message.reply_text(
        f"👤 الزبون: **{selected_name}**\n\n💵 أدخل **مبلغ الدين**:",
        parse_mode='Markdown',
        reply_markup=ReplyKeyboardRemove()
    )
    return ADD_WAITING_FOR_AMOUNT

async def add_process_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text.strip())
        context.user_data['amount'] = amount
    except ValueError:
        await update.message.reply_text("⚠️ يرجى إدخال رقم صحيح للمبلغ:")
        return ADD_WAITING_FOR_AMOUNT

    await update.message.reply_text(
        "📝 أدخل **نوع الدين** (الوصف):\n\nمثال: `5 قهوة + 2 بلياردو`",
        parse_mode='Markdown'
    )
    return ADD_WAITING_FOR_TYPE

async def add_save_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    item_type = update.message.text.strip()
    name = context.user_data.get('selected_name')
    amount = context.user_data.get('amount')
    current_date = datetime.now().strftime("%Y-%m-%d %H:%M")

    await update.message.reply_text("⏳ جاري حفظ البيانات في جوجل شيت...")

    try:
        total_sheet, debt_log_sheet, _ = get_sheets()
        
        # 1. حفظ في "سجل الديون"
        debt_log_sheet.append_row([name, amount, item_type, current_date])

        # 2. تحديث "الديون الإجمالية"
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

        await update.message.reply_text(
            f"✅ **تم إضافة الدين بنجاح!**\n\n"
            f"👤 **الاسم:** {name}\n"
            f"💵 **المبلغ:** {amount}\n"
            f"📝 **النوع:** {item_type}\n"
            f"📅 **التاريخ:** {current_date}\n\n"
            f"💰 **إجمالي الدين الحالي:** {new_amount}",
            parse_mode='Markdown',
            reply_markup=main_menu_keyboard()
        )
    except Exception as e:
        await update.message.reply_text(f"❌ حدث خطأ أثناء الحفظ: {e}", reply_markup=main_menu_keyboard())

    context.user_data.clear()
    return ConversationHandler.END

# --- 5. محادثة [💳 سداد دين] ---

async def start_pay_debt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    names_markup, err, count = build_names_keyboard()
    if err:
        await update.message.reply_text(f"❌ حدث خطأ في الاتصال بجوجل شيت:\n`{err}`", parse_mode='Markdown')
        return ConversationHandler.END
    elif count == 0:
        await update.message.reply_text("⚠️ لم يتم العثور على أي أسماء في صفحة الديون الإجمالية!", reply_markup=main_menu_keyboard())
        return ConversationHandler.END
    
    await update.message.reply_text("💳 (سداد دين) اختر اسم الزبون من القائمة:", reply_markup=names_markup)
    return PAY_WAITING_FOR_NAME

async def pay_process_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "❌ إلغاء العملية":
        return await cancel(update, context)
        
    selected_name = text.replace("👤 ", "").strip()
    context.user_data['selected_name'] = selected_name
    
    await update.message.reply_text(
        f"👤 الزبون: **{selected_name}**\n\n💵 أدخل **مبلغ السداد**:",
        parse_mode='Markdown',
        reply_markup=ReplyKeyboardRemove()
    )
    return PAY_WAITING_FOR_AMOUNT

async def pay_process_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text.strip())
        context.user_data['amount'] = amount
    except ValueError:
        await update.message.reply_text("⚠️ يرجى إدخال رقم صحيح للمبلغ:")
        return PAY_WAITING_FOR_AMOUNT

    await update.message.reply_text(
        "💼 اختر **المحفظة** التي تم السداد عليها:",
        reply_markup=wallet_keyboard()
    )
    return PAY_WAITING_FOR_WALLET

async def pay_save_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    wallet = update.message.text.strip()
    if wallet == "❌ إلغاء العملية":
        return await cancel(update, context)

    name = context.user_data.get('selected_name')
    amount = context.user_data.get('amount')
    current_date = datetime.now().strftime("%Y-%m-%d %H:%M")

    await update.message.reply_text("⏳ جاري تسجيل عملية السداد...")

    try:
        total_sheet, _, pay_log_sheet = get_sheets()
        
        # 1. حفظ في "سجل السداد" (الاسم، المبلغ، المحفظة، التاريخ)
        pay_log_sheet.append_row([name, amount, wallet, current_date])

        # 2. خصم المبلغ من "الديون الإجمالية"
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

        await update.message.reply_text(
            f"✅ **تم تسجيل السداد بنجاح!**\n\n"
            f"👤 **الاسم:** {name}\n"
            f"💵 **المبلغ المسدد:** {amount}\n"
            f"💼 **المحفظة:** {wallet}\n"
            f"📅 **التاريخ:** {current_date}\n\n"
            f"{msg_total}",
            parse_mode='Markdown',
            reply_markup=main_menu_keyboard()
        )
    except Exception as e:
        await update.message.reply_text(f"❌ حدث خطأ أثناء التسجيل: {e}", reply_markup=main_menu_keyboard())

    context.user_data.clear()
    return ConversationHandler.END

# --- 6. التشغيل الرئيسي ---
if __name__ == '__main__':
    keep_alive()
    
    TOKEN = "8718346069:AAHWbPMhPLiOMOtM_zGUZZjWg133U5EtyE0"
    
    app = ApplicationBuilder().token(TOKEN).build()
    
    # محادثة إضافة الدين
    add_debt_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^➕ إضافة دين$"), start_add_debt)],
        states={
            ADD_WAITING_FOR_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_process_name)],
            ADD_WAITING_FOR_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_process_amount)],
            ADD_WAITING_FOR_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_save_final)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            MessageHandler(filters.Regex("^❌ إلغاء العملية$"), cancel)
        ]
    )

    # محادثة سداد الدين
    pay_debt_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^💳 سداد دين$"), start_pay_debt)],
        states={
            PAY_WAITING_FOR_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, pay_process_name)],
            PAY_WAITING_FOR_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, pay_process_amount)],
            PAY_WAITING_FOR_WALLET: [MessageHandler(filters.TEXT & ~filters.COMMAND, pay_save_final)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            MessageHandler(filters.Regex("^❌ إلغاء العملية$"), cancel)
        ]
    )
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(add_debt_conv)
    app.add_handler(pay_debt_conv)
    
    print("البوت يعمل الآن...")
    app.run_polling()
