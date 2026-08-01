import os
import json
from threading import Thread
from datetime import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters
from flask import Flask

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

# --- 1. الإتصال بجوجل شيت (معدّل للعمل بأمان عبر Environment Variable) ---
def get_sheets():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    
    # القراءة من متغيرة البيئة الآمنة على Render
    if "GOOGLE_CREDENTIALS" in os.environ:
        creds_dict = json.loads(os.environ["GOOGLE_CREDENTIALS"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    else:
        # قراءة محلية للتشغيل التجريبي على اللابتوب
        creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
        
    client = gspread.authorize(creds)
    
    spreadsheet = client.open("كفي الشرفا")
    
    # الورقة الأولى للديون الإجمالية
    debts_sheet = spreadsheet.get_worksheet(0) 
    
    try:
        log_sheet = spreadsheet.worksheet("سجل الحركات")
    except Exception:
        log_sheet = debts_sheet
        
    return debts_sheet, log_sheet

# --- 2. لوحات الأزرار بعرض الشاشة ---

def main_menu_keyboard():
    keyboard = [
        [KeyboardButton("➕ إضافة دين")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# بناء لوحة الأسماء من العمود A المباشر
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
        
    keyboard.append([KeyboardButton("🔙 القائمة الرئيسية")])
    
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True), error_msg, len(names)

# --- 3. الأوامر ووظائف البوت ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "مرحباً بك! اضغط على الزر بالأسفل لإضافة دين:",
        reply_markup=main_menu_keyboard()
    )

async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    
    if text == "➕ إضافة دين":
        names_markup, err, count = build_names_keyboard()
        
        if err:
            await update.message.reply_text(f"❌ حدث خطأ في الاتصال بجوجل شيت:\n`{err}`", parse_mode='Markdown')
        elif count == 0:
            await update.message.reply_text("⚠️ لم يتم العثور على أي أسماء في العمود A داخل الشيت!", reply_markup=names_markup)
        else:
            await update.message.reply_text("📋 اختر اسم الزبون من القائمة:", reply_markup=names_markup)
        
    elif text == "🔙 القائمة الرئيسية":
        await update.message.reply_text(
            "تم العودة للقائمة الرئيسية:",
            reply_markup=main_menu_keyboard()
        )
        
    elif text.startswith("👤 "):
        selected_name = text.replace("👤 ", "").strip()
        msg = (
            f"✍️ **إضافة دين لـ ({selected_name}):**\n\n"
            f"انسخ الأمر وعدّل عليه المبلغ والوصف ثم أرسله:\n"
            f"`/add {selected_name} 2 قهوة 10`"
        )
        await update.message.reply_text(msg, parse_mode='Markdown')

async def add_debt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if len(context.args) < 3:
            raise IndexError

        name = context.args[0].strip().lower()
        amount = float(context.args[-1])
        item_description = " ".join(context.args[1:-1])
        date_str = datetime.now().strftime("%Y-%m-%d %H:%M")

        debts_sheet, log_sheet = get_sheets()
        
        try:
            log_sheet.append_row([name, item_description, amount, date_str])
        except Exception:
            pass

        col_values = [v.lower() for v in debts_sheet.col_values(1)]
        
        if name in col_values:
            row_index = col_values.index(name) + 1
            cell_val = debts_sheet.cell(row_index, 2).value
            current_amount = float(cell_val) if cell_val else 0.0
            new_amount = current_amount + amount
            debts_sheet.update_cell(row_index, 2, new_amount)
        else:
            new_amount = amount
            debts_sheet.append_row([name, new_amount])
            
        await update.message.reply_text(
            f"✅ تم إضافة **({item_description})** بقيمة **{amount}** على الزبون **{name}**.\n"
            f"💰 إجمالي الدين الحالي: **{new_amount}**", 
            parse_mode='Markdown',
            reply_markup=main_menu_keyboard()
        )
    except (IndexError, ValueError):
        await update.message.reply_text("⚠️ طريقة الاستخدام الخاطئة!\nالشكل الصحيح: `/add عبود الشرفا 2 كاسة قهوة 10`", parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"❌ حدث خطأ: {e}")

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
        await update.message.reply_text("⚠️ طريقة الاستخدام الخاطئة!\nالشكل الصحيح: `/pay عبود الشرفا 5`", parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"❌ حدث خطأ: {e}")

# --- 4. التشغيل ---
if __name__ == '__main__':
    keep_alive()
    
    TOKEN = "8718346069:AAHWbPMhPLiOMOtM_zGUZZjWg133U5EtyE0"
    
    app = ApplicationBuilder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", add_debt))
    app.add_handler(CommandHandler("pay", pay_debt))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_buttons))
    
    print("البوت يعمل الآن...")
    app.run_polling()
