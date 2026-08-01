import os
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

# --- 1. الإتصال بجوجل شيت ---
def get_sheets():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
    client = gspread.authorize(creds)
    
    spreadsheet = client.open("كفي الشرفا")
    
    debts_sheet = spreadsheet.worksheet("الديون الإجمالية")
    log_sheet = spreadsheet.worksheet("سجل الحركات")
    return debts_sheet, log_sheet

# --- 2. لوحات الأزرار بعرض الشاشة ---

# الزر الرئيسي الوحيد بعرض الشاشة
def main_menu_keyboard():
    keyboard = [
        [KeyboardButton("➕ إضافة دين")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# قائمة الأسماء (جلب العمود A مباشرة لضمان ظهور جميع الأسماء)
def build_names_keyboard():
    try:
        debts_sheet, _ = get_sheets()
        # جلب كل القيم الموجودة في العمود الأول A
        col_values = debts_sheet.col_values(1)
        # استبعاد الترويسة "الاسم" أو "الإسم" والصفوف الفارغة
        names = [val.strip() for val in col_values if val.strip() and val.strip() not in ["الاسم", "الإسم"]]
    except Exception as e:
        print(f"Error fetching names: {e}")
        names = []

    keyboard = []
    
    # وضع كل اسم في زر منفصل بعرض الشاشة
    for name in names:
        keyboard.append([KeyboardButton(f"👤 {name}")])
        
    # زر الرجوع للقائمة الرئيسية
    keyboard.append([KeyboardButton("🔙 القائمة الرئيسية")])
    
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# --- 3. الأوامر ووظائف البوت ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "مرحباً بك! اضغط على الزر بالأسفل لإضافة دين:",
        reply_markup=main_menu_keyboard()
    )

async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    
    if text == "➕ إضافة دين":
        await update.message.reply_text(
            "📋 اختر اسم الزبون من القائمة:",
            reply_markup=build_names_keyboard()
        )
        
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
        log_sheet.append_row([name, item_description, amount, date_str])

        col_values = [v.lower() for v in debts_sheet.col_values(1)]
        
        row_index = None
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
            log_sheet.append_row([name, "تسديد دفعة", -amount, date_str])
            
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

async def check_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        name = context.args[0].strip().lower()
        debts_sheet, log_sheet = get_sheets()
        
        logs = log_sheet.get_all_records()
        customer_logs = [l for l in logs if str(l.get('الاسم', '')).strip().lower() == name]
        
        if not customer_logs:
            await update.message.reply_text(f"❌ لا يوجد أي سجلات أو ديون باسم **{name}**.", parse_mode='Markdown')
            return

        msg = f"🔍 **كشف حساب الزبون ({name}):**\n\n"
        total = 0
        for item in customer_logs:
            msg += f"• {item.get('الوصف', '')} | {item.get('المبلغ', 0)} | ({item.get('التاريخ', '')})\n"
            total += float(item.get('المبلغ', 0))
            
        msg += f"\n💰 **الصافي المتبقي عليه:** {total}"
        await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=main_menu_keyboard())

    except IndexError:
        await update.message.reply_text("⚠️ يرجى كتابة اسم الزبون، مثال:\n`/check عبود الشرفا`", parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"❌ حدث خطأ: {e}")

async def list_debts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        debts_sheet, _ = get_sheets()
        names = debts_sheet.col_values(1)[1:]
        amounts = debts_sheet.col_values(2)[1:]
        
        if not names:
            await update.message.reply_text("🎉 لا يوجد أي ديون مسجلة حالياً!", reply_markup=main_menu_keyboard())
            return
            
        msg = "📋 **قائمة الديون الإجمالية:**\n\n"
        total_all = 0
        for n, a in zip(names, amounts):
            val = float(a) if a else 0.0
            msg += f"• **{n}**: {val}\n"
            total_all += val
            
        msg += f"\n💰 **إجمالي الديون للجميع:** {total_all}"
        await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=main_menu_keyboard())
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
    app.add_handler(CommandHandler("check", check_customer))
    app.add_handler(CommandHandler("list", list_debts))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_buttons))
    
    print("البوت يعمل الآن بالتحديث المباشر للعمود A...")
    app.run_polling()
