import os
from threading import Thread
from datetime import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, CallbackQueryHandler, filters
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

# --- 2. بناء الـ Reply Keyboard بزر واحد ---
def build_reply_keyboard():
    keyboard = [[KeyboardButton("➕ إضافة دين")]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# --- 3. الأوامر ووظائف البوت ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # إظهار الـ Reply Keyboard مباشرة بدون رسائل تعليمات طويلة
    await update.message.reply_text(
        "👇 اختر الاسم من القائمة لإضافة دين أو اضغط تحديث:",
        reply_markup=build_reply_keyboard()
    )

async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    state = context.user_data.get('state')
    
    if text == "➕ إضافة دين":
        context.user_data['state'] = None
        context.user_data['selected_customer'] = None
        
        processing_msg = await update.message.reply_text("⏳ جاري جلب أسماء الزبائن من جوجل شيت...")
        try:
            debts_sheet, _ = get_sheets()
            names = debts_sheet.col_values(1)[1:]  # تخطي صف العناوين
            
            # تنظيف الأسماء وإزالة المكرر والفارغ
            seen = set()
            unique_names = []
            for n in names:
                n_clean = n.strip()
                if n_clean and n_clean.lower() not in seen:
                    seen.add(n_clean.lower())
                    unique_names.append(n_clean)
            
            keyboard = []
            row = []
            for name in unique_names:
                row.append(InlineKeyboardButton(name, callback_data=f"select_customer:{name}"))
                if len(row) == 2:
                    keyboard.append(row)
                    row = []
            if row:
                keyboard.append(row)
                
            keyboard.append([InlineKeyboardButton("➕ زبون غير مسجل", callback_data="new_customer")])
            keyboard.append([InlineKeyboardButton("❌ إلغاء العملية", callback_data="cancel_action")])
            
            await processing_msg.delete()
            await update.message.reply_text(
                "👤 **اختر اسم الزبون من القائمة:**",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
        except Exception as e:
            try:
                await processing_msg.delete()
            except Exception:
                pass
            await update.message.reply_text(f"❌ فشل جلب الأسماء من جوجل شيت: {e}\n\nيمكنك استخدام الأمر المباشر:\n`/add الاسم الوصف المبلغ`")
        return

    # معالجة الحالات (Conversational States)
    if state == 'WAITING_FOR_NEW_CUSTOMER_NAME':
        name = text.strip()
        if not name:
            await update.message.reply_text("⚠️ يرجى إدخال اسم صحيح:")
            return
        context.user_data['selected_customer'] = name
        context.user_data['state'] = 'WAITING_FOR_DEBT_DETAILS'
        await update.message.reply_text(
            f"👤 تم تحديد الزبون: **{name}**\n\n"
            f"✍️ الآن، يرجى إرسال التفاصيل والمبلغ بالصيغة التالية:\n"
            f"`التفاصيل المبلغ`\n\n"
            f"*مثال:* `2 قهوة 10`",
            parse_mode='Markdown'
        )
        return
        
    elif state == 'WAITING_FOR_DEBT_DETAILS':
        parts = text.strip().split()
        if len(parts) < 2:
            await update.message.reply_text(
                "⚠️ صيغة خاطئة! يرجى إرسال التفاصيل والمبلغ معاً.\n"
                "*مثال:* `2 قهوة 10`",
                parse_mode='Markdown'
            )
            return
        
        try:
            amount = float(parts[-1])
            item_description = " ".join(parts[:-1])
            name = context.user_data.get('selected_customer').strip().lower()
            date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
            
            processing_msg = await update.message.reply_text("⏳ جاري إضافة الدين إلى جوجل شيت...")
            
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
                
            context.user_data['state'] = None
            context.user_data['selected_customer'] = None
            
            try:
                await processing_msg.delete()
            except Exception:
                pass
                
            await update.message.reply_text(
                f"✅ تم إضافة **({item_description})** بقيمة **{amount}** على الزبون **{name}**.\n"
                f"💰 إجمالي الدين الحالي: **{new_amount}**", 
                parse_mode='Markdown',
                reply_markup=build_reply_keyboard()
            )
        except ValueError:
            await update.message.reply_text("⚠️ يرجى التأكد من إدخال رقم صحيح للمبلغ في نهاية الرسالة (مثال: `2 قهوة 10`):")
        except Exception as e:
            try:
                await processing_msg.delete()
            except Exception:
                pass
            await update.message.reply_text(f"❌ حدث خطأ أثناء الحفظ: {e}")
        return

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data.startswith("select_customer:"):
        name = data.split(":", 1)[1]
        context.user_data['selected_customer'] = name
        context.user_data['state'] = 'WAITING_FOR_DEBT_DETAILS'
        
        await query.edit_message_text(
            text=f"👤 تم اختيار الزبون: **{name}**\n\n"
                 f"✍️ يرجى إرسال التفاصيل والمبلغ بالصيغة التالية:\n"
                 f"`التفاصيل المبلغ`\n\n"
                 f"*مثال:* `2 قهوة 10`",
            parse_mode='Markdown'
        )
        
    elif data == "new_customer":
        context.user_data['state'] = 'WAITING_FOR_NEW_CUSTOMER_NAME'
        await query.edit_message_text(
            text="✍️ **إضافة زبون جديد:**\n\n"
                 "يرجى إرسال اسم الزبون الجديد في رسالة نصية."
        )
        
    elif data == "cancel_action":
        context.user_data['state'] = None
        context.user_data['selected_customer'] = None
        await query.edit_message_text(
            text="❌ تم إلغاء العملية."
        )


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
            parse_mode='Markdown',
            reply_markup=build_reply_keyboard()
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
                
            await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=build_reply_keyboard())
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
        await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=build_reply_keyboard())

    except IndexError:
        await update.message.reply_text("⚠️ يرجى كتابة اسم الزبون، مثال:\n`/check أحمد`", parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"❌ حدث خطأ: {e}")

async def list_debts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        debts_sheet, _ = get_sheets()
        records = debts_sheet.get_all_records()
        
        if not records:
            await update.message.reply_text("🎉 لا يوجد أي ديون مسجلة حالياً!", reply_markup=build_reply_keyboard())
            return
            
        msg = "📋 **قائمة الديون الإجمالية:**\n\n"
        total_all = 0
        for rec in records:
            name = rec['الاسم']
            amount = float(rec['المبلغ'])
            msg += f"• **{name}**: {amount}\n"
            total_all += amount
            
        msg += f"\n💰 **إجمالي الديون للجميع:** {total_all}"
        await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=build_reply_keyboard())
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
    
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_buttons))
    
    print("البوت يعمل الآن بالتسميات العربية ومجهّز لـ Render...")
    app.run_polling()
