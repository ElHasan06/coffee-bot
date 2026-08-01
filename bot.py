import os
from threading import Thread
from datetime import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
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
    spreadsheet = client.open("ديون الكافيه")
    
    debts_sheet = spreadsheet.worksheet("الديون الإجمالية")
    log_sheet = spreadsheet.worksheet("سجل الحركات")
    return debts_sheet, log_sheet

# --- 2. الأوامر ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "☕ **مرحباً بك في بوت إدارة ديون الكافيه**\n\n"
        "الأوامر المتاحة:\n"
        "➕ `/add الاسم الوصف المبلغ` - إضافة دين مفصل\n"
        "   *مثال:* `/add أحمد 2 كاسة قهوة 10`\n\n"
        "➖ `/pay الاسم المبلغ` - خصم/تسديد مبلغ\n"
        "   *مثال:* `/pay أحمد 5`\n\n"
        "📋 `/list` - عرض قائمة جميع الديون الإجمالية\n"
        "🔍 `/check الاسم` - عرض كشف حساب مفصل لزبون معين"
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')

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

        records = debts_sheet.get_all_records()
        row_index = None
        current_amount = 0
        
        for i, rec in enumerate(records, start=2):
            if str(rec['الاسم']).strip().lower() == name:
                row_index = i
                current_amount = float(rec['المبلغ'])
                break
                
        if row_index:
            new_amount = current_amount + amount
            debts_sheet.update_cell(row_index, 2, new_amount)
        else:
            new_amount = amount
            debts_sheet.append_row([name, new_amount])
            
        await update.message.reply_text(
            f"✅ تم إضافة **({item_description})** بقيمة **{amount}** على الزبون **{name}**.\n"
            f"💰 إجمالي الدين الحالي: **{new_amount}**", 
            parse_mode='Markdown'
        )
    except (IndexError, ValueError):
        await update.message.reply_text("⚠️ طريقة الاستخدام الخاطئة!\nالشكل الصحيح: `/add أحمد 2 كاسة قهوة 10`", parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"❌ حدث خطأ: {e}")

async def pay_debt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        name = context.args[0].strip().lower()
        amount = float(context.args[1])
        date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        debts_sheet, log_sheet = get_sheets()
        records = debts_sheet.get_all_records()
        
        row_index = None
        current_amount = 0
        
        for i, rec in enumerate(records, start=2):
            if str(rec['الاسم']).strip().lower() == name:
                row_index = i
                current_amount = float(rec['المبلغ'])
                break
                
        if row_index:
            new_amount = current_amount - amount
            log_sheet.append_row([name, "تسديد دفعة", -amount, date_str])
            
            if new_amount <= 0:
                debts_sheet.delete_rows(row_index)
                msg = f"🎉 تم تسديد الدين بالكامل لـ **{name}** وتم حذفه من القائمة الرئيسية!"
            else:
                debts_sheet.update_cell(row_index, 2, new_amount)
                msg = f"📉 تم خصم **{amount}** من **{name}**.\nالمتبقي عليه: **{new_amount}**"
                
            await update.message.reply_text(msg, parse_mode='Markdown')
        else:
            await update.message.reply_text(f"❌ الزبون **{name}** غير موجود في قائمة الديون.", parse_mode='Markdown')
            
    except (IndexError, ValueError):
        await update.message.reply_text("⚠️ طريقة الاستخدام الخاطئة!\nالشكل الصحيح: `/pay أحمد 5`", parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"❌ حدث خطأ: {e}")

async def check_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        name = context.args[0].strip().lower()
        debts_sheet, log_sheet = get_sheets()
        
        logs = log_sheet.get_all_records()
        customer_logs = [l for l in logs if str(l['الاسم']).strip().lower() == name]
        
        if not customer_logs:
            await update.message.reply_text(f"❌ لا يوجد أي سجلات أو ديون باسم **{name}**.", parse_mode='Markdown')
            return

        msg = f"🔍 **كشف حساب الزبون ({name}):**\n\n"
        total = 0
        for item in customer_logs:
            msg += f"• {item['الوصف']} | {item['المبلغ']} | ({item['التاريخ']})\n"
            total += float(item['المبلغ'])
            
        msg += f"\n💰 **الصافي المتبقي عليه:** {total}"
        await update.message.reply_text(msg, parse_mode='Markdown')

    except IndexError:
        await update.message.reply_text("⚠️ يرجى كتابة اسم الزبون، مثال:\n`/check أحمد`", parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"❌ حدث خطأ: {e}")

async def list_debts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        debts_sheet, _ = get_sheets()
        records = debts_sheet.get_all_records()
        
        if not records:
            await update.message.reply_text("🎉 لا يوجد أي ديون مسجلة حالياً!")
            return
            
        msg = "📋 **قائمة الديون الإجمالية:**\n\n"
        total_all = 0
        for rec in records:
            name = rec['الاسم']
            amount = float(rec['المبلغ'])
            msg += f"• **{name}**: {amount}\n"
            total_all += amount
            
        msg += f"\n💰 **إجمالي الديون للجميع:** {total_all}"
        await update.message.reply_text(msg, parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"❌ حدث خطأ: {e}")

# --- 3. التشغيل ---
if __name__ == '__main__':
    # تشغيل خادم الويب في الخلفية
    keep_alive()
    
    TOKEN = "8718346069:AAHWbPMhPLiOMOtM_zGUZZjWg133U5EtyE0"
    
    app = ApplicationBuilder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", add_debt))
    app.add_handler(CommandHandler("pay", pay_debt))
    app.add_handler(CommandHandler("check", check_customer))
    app.add_handler(CommandHandler("list", list_debts))
    
    print("البوت يعمل الآن بالتسميات العربية ومجهّز لـ Render...")
    app.run_polling()
