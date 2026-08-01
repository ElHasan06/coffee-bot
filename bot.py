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

# --- مراحل المحادثة (Conversation States) ---
WAITING_FOR_AMOUNT, WAITING_FOR_TYPE = range(2)

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
    
    debts_sheet = spreadsheet.get_worksheet(0) 
    
    try:
        log_sheet = spreadsheet.worksheet("سجل الحركات")
    except Exception:
        log_sheet = debts_sheet
        
    return debts_sheet, log_sheet

# --- 2. لوحات الأزرار ---

def main_menu_keyboard():
    keyboard = [
        [KeyboardButton("➕ إضافة دين")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def build_names_keyboard():
    error_msg = None
    try:
        debts_sheet, _ = get_sheets()
        col_values = debts_sheet.col_values(1)
        names = [val.strip() for val in col_values if val.strip() and val.strip() not in ["الاسم", "الإسم"]]
    except Exception as e:
        names = []
        error_msg = str(e)

    keyboard = []
    for name in names:
        keyboard.append([KeyboardButton(f"👤 {name}")])
        
    keyboard.append([KeyboardButton("❌ إلغاء العملية")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True), error_msg, len(names)

# --- 3. دالّات المحادثة والتشغيل ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "مرحباً بك! اضغط على الزر بالأسفل لإضافة دين:",
        reply_markup=main_menu_keyboard()
    )

# 1️⃣ البدء واختيار الاسم
async def start_add_debt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    names_markup, err, count = build_names_keyboard()
    
    if err:
        await update.message.reply_text(f"❌ حدث خطأ في الاتصال بجوجل شيت:\n`{err}`", parse_mode='Markdown')
        return ConversationHandler.END
    elif count == 0:
        await update.message.reply_text("⚠️ لم يتم العثور على أي أسماء في العمود A داخل الشيت!", reply_markup=names_markup)
        return ConversationHandler.END
    else:
        await update.message.reply_text("📋 اختر اسم الزبون من القائمة:", reply_markup=names_markup)
        return WAITING_FOR_AMOUNT

# 2️⃣ استقبال المبلغ والطلب للنوع
async def process_name_and_ask_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    
    if text == "❌ إلغاء العملية":
        await update.message.reply_text("تم إلغاء العملية.", reply_markup=main_menu_keyboard())
        return ConversationHandler.END
        
    selected_name = text.replace("👤 ", "").strip()
    context.user_data['selected_name'] = selected_name
    
    await update.message.reply_text(
        f"👤 الزبون: **{selected_name}**\n\n💵 أدخل **مبلغ الدين** (أرقام فقط):",
        parse_mode='Markdown',
        reply_markup=ReplyKeyboardRemove()
    )
    return WAITING_FOR_TYPE

# 3️⃣ استقبال النوع وحفظ البيانات بالكامل في Google Sheet
async def process_amount_and_ask_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    amount_text = update.message.text.strip()
    
    # التأكد أن الادخال رقم
    try:
        amount = float(amount_text)
        context.user_data['amount'] = amount
    except ValueError:
        await update.message.reply_text("⚠️ يرجى إدخال رقم صحيح للمبلغ (مثال: 15 أو 10.5):")
        return WAITING_FOR_TYPE

    await update.message.reply_text(
        "📝 أدخل **نوع الدين** (الوصف):\n\nمثال: `5 قهوة + 2 بلياردو`",
        parse_mode='Markdown'
    )
    return 3 # انتقال لخطوة الحفظ النهائي

async def save_debt_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    item_type = update.message.text.strip()
    name = context.user_data.get('selected_name')
    amount = context.user_data.get('amount')
    
    # جلب الوقت والتاريخ الحالي من الجهاز
    current_date = datetime.now().strftime("%Y-%m-%d %H:%M")

    await update.message.reply_text("⏳ جاري حفظ البيانات في جوجل شيت...")

    try:
        debts_sheet, log_sheet = get_sheets()
        
        # 1. إضافة الحركة في ورقة "سجل الحركات" (الاسم، النوع، المبلغ، التاريخ)
        try:
            log_sheet.append_row([name, item_type, amount, current_date])
        except Exception as e:
            print(f"Log sheet error: {e}")

        # 2. تحديث المجموع في الورقة الرئيسية
        col_values = [v.lower() for v in debts_sheet.col_values(1)]
        search_name = name.lower()
        
        if search_name in col_values:
            row_index = col_values.index(search_name) + 1
            cell_val = debts_sheet.cell(row_index, 2).value
            current_amount = float(cell_val) if cell_val else 0.0
            new_amount = current_amount + amount
            debts_sheet.update_cell(row_index, 2, new_amount)
        else:
            new_amount = amount
            debts_sheet.append_row([name, new_amount])

        await update.message.reply_text(
            f"✅ **تم الحفظ بنجاح!**\n\n"
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

    # إخلاء البيانات المؤقتة
    context.user_data.clear()
    return ConversationHandler.END

# دالة إلغاء المحادثة في أي وقت
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("تم إلغاء العملية.", reply_markup=main_menu_keyboard())
    return ConversationHandler.END

# --- 4. التسديد السريع ---
async def pay_debt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        name = context.args[0].strip().lower()
        amount = float(context.args[1])
        date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        debts_sheet, log_sheet = get_sheets()
        col_values = [v.lower() for v in debts_sheet.col_values(1)]
        
        if name in col_values:
            row_index = col_values.index(name) + 1
            cell_val = debts_sheet.cell(row_index, 2).value
            current_amount = float(cell_val) if cell_val else 0.0
            
            new_amount = current_amount - amount
            try:
                log_sheet.append_row([name, "تسديد دفعة", -amount, date_str])
            except Exception:
                pass
            
            if new_amount <= 0:
                debts_sheet.delete_rows(row_index)
                msg = f"🎉 تم تسديد الدين بالكامل لـ **{name}** وتم حذفه من القائمة الرئيسية!"
            else:
                debts_sheet.update_cell(row_index, 2, new_amount)
                msg = f"📉 تم خصم **{amount}** من **{name}**.\nالمتبقي عليه: **{new_amount}**"
                
            await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=main_menu_keyboard())
        else:
            await update.message.reply_text(f"❌ الزبون **{name}** غير موجود في قائمة الديون.", parse_mode='Markdown')
            
    except (IndexError, ValueError):
        await update.message.reply_text("⚠️ طريقة الاستخدام:\n`/pay الاسم المبلغ`", parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"❌ حدث خطأ: {e}")

# --- 5. التشغيل الرئيسي ---
if __name__ == '__main__':
    keep_alive()
    
    TOKEN = "8718346069:AAHWbPMhPLiOMOtM_zGUZZjWg133U5EtyE0"
    
    app = ApplicationBuilder().token(TOKEN).build()
    
    # معالج خطوات المحادثة (إضافة الدين)
    add_debt_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^➕ إضافة دين$"), start_add_debt)],
        states={
            WAITING_FOR_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_name_and_ask_amount)],
            WAITING_FOR_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_amount_and_ask_type)],
            3: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_debt_final)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            MessageHandler(filters.Regex("^❌ إلغاء العملية$"), cancel)
        ]
    )
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("pay", pay_debt))
    app.add_handler(add_debt_conv)
    
    print("البوت يعمل الآن...")
    app.run_polling()
