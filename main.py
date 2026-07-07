import os
import sys
import json
import shutil
import zipfile
import subprocess
import asyncio
import re
import time
from datetime import datetime, timedelta
from pyrogram import Client, filters
from pyrogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, Message

# ================= إعدادات البوت =================
API_ID = 24217199
API_HASH = "11c12a66dbd23da592211771db1bce6b"
BOT_TOKEN = "7556780940:AAGiqplcTzxdJi4vQ_xUKv34Md9JotDQZY0"
ADMIN_ID = 6019481812

app = Client("HostingManager", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ================= قاعدة البيانات =================
DB_FILE = "database.json"

if not os.path.exists(DB_FILE):
    with open(DB_FILE, "w") as f:
        json.dump({"users": {}, "banned": [], "locked": False, "vip": {}}, f)

def load_db():
    with open(DB_FILE, "r") as f:
        return json.load(f)

def save_db(data):
    with open(DB_FILE, "w") as f:
        json.dump(data, f, indent=4)

user_states = {}
running_bots = {}

# ================= دوال مساعدة =================

def is_vip(user_id):
    db = load_db()
    vip_data = db.get("vip", {})
    uid = str(user_id)
    if uid in vip_data:
        expiry = vip_data[uid]
        if expiry > time.time():
            return True
        else:
            # انتهت صلاحية الـ VIP، نزيلها تلقائياً
            del vip_data[uid]
            db["vip"] = vip_data
            save_db(db)
    return False

def get_user_limit(user_id):
    if user_id == ADMIN_ID:
        return 999
    if is_vip(user_id):
        return 999  # غير محدود
    db = load_db()
    uid = str(user_id)
    if uid not in db["users"]:
        db["users"][uid] = 2
        save_db(db)
    return db["users"][uid]

def get_active_slots(user_id):
    base_dir = f"hostings/{user_id}"
    if not os.path.exists(base_dir):
        return []
    slots = []
    for d in os.listdir(base_dir):
        if d.startswith("slot_"):
            try:
                slots.append(int(d.split("_")[1]))
            except:
                continue
    return sorted(slots)

def find_main_script(bot_dir):
    for root, _, files in os.walk(bot_dir):
        if "main.py" in files:
            return os.path.join(root, "main.py")
        for file in files:
            if file.endswith(".py"):
                return os.path.join(root, file)
    return None

def auto_install_requirements(bot_dir, script_path):
    req_file = os.path.join(os.path.dirname(script_path), "requirements.txt")
    if not os.path.exists(req_file):
        req_file = os.path.join(bot_dir, "requirements.txt")
    if os.path.exists(req_file):
        subprocess.run(["pip", "install", "-r", req_file], capture_output=True)
    else:
        try:
            with open(script_path, "r", encoding="utf-8") as f:
                content = f.read()
            imports = set()
            for line in content.split("\n"):
                match = re.match(r'^\s*(?:import|from)\s+([a-zA-Z0-9_]+)', line)
                if match:
                    mod = match.group(1)
                    if mod not in sys.builtin_module_names and mod not in ["os", "sys", "json", "time", "datetime", "re"]:
                        imports.add(mod)
            if imports:
                subprocess.run(["pip", "install"] + list(imports), capture_output=True)
        except:
            pass

async def check_disk_space(client):
    total, used, free = shutil.disk_usage("/")
    percent = (used / total) * 100
    if percent >= 85:
        await client.send_message(ADMIN_ID, f"⚠️ **تحذير:** مساحة الاستضافة وصلت إلى {percent:.1f}%!")

def normalize_zip_extraction(zip_path, extract_to):
    """
    تستخرج الملفات، وإذا كان هناك مجلد واحد في الجذر، تنقل محتوياته إلى extract_to.
    """
    temp_dir = os.path.join(os.path.dirname(zip_path), "temp_extract")
    os.makedirs(temp_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(temp_dir)
    items = os.listdir(temp_dir)
    if len(items) == 1 and os.path.isdir(os.path.join(temp_dir, items[0])):
        # مجلد واحد فقط، انقل محتوياته
        src_folder = os.path.join(temp_dir, items[0])
        for item in os.listdir(src_folder):
            shutil.move(os.path.join(src_folder, item), extract_to)
        shutil.rmtree(temp_dir)
    else:
        # انقل كل الملفات والمجلدات إلى الوجهة
        for item in items:
            shutil.move(os.path.join(temp_dir, item), extract_to)
        shutil.rmtree(temp_dir)

# ================= لوحات المفاتيح =================

def main_menu(user_id):
    btns = [[KeyboardButton("تنصيب بوت"), KeyboardButton("حذف تنصيب")]]
    if user_id == ADMIN_ID:
        btns.append([KeyboardButton("إدارة بوتك"), KeyboardButton("إدارة بوتات الأعضاء")])
        btns.append([KeyboardButton("قفل التنصيب"), KeyboardButton("تشغيل التنصيب")])
        btns.append([KeyboardButton("جلب نسخة احتياطية"), KeyboardButton("رفع نسخة احتياطية")])
        btns.append([KeyboardButton("الإحصائيات والتقرير"), KeyboardButton("المنصبين")])
        btns.append([KeyboardButton("رفع عضو VIP"), KeyboardButton("تنزيل عضو VIP")])
        btns.append([KeyboardButton("عرض الأعضاء VIP")])
    else:
        btns.append([KeyboardButton("قسم الإدارة")])
    return ReplyKeyboardMarkup(btns, resize_keyboard=True)

def manage_menu():
    return ReplyKeyboardMarkup([
        [KeyboardButton("سجل البوت"), KeyboardButton("حالة البوت")],
        [KeyboardButton("إيقاف مؤقت"), KeyboardButton("تشغيل البوت"), KeyboardButton("🔄 إعادة تشغيل")],
        [KeyboardButton("⌨️ إدخال بيانات"), KeyboardButton("📂 إدارة الملفات")],
        [KeyboardButton("رجوع")]
    ], resize_keyboard=True)

def file_manage_menu():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📄 عرض الملفات"), KeyboardButton("📁 دخول مجلد")],
        [KeyboardButton("➕ إضافة ملف"), KeyboardButton("🔄 تبديل ملف"), KeyboardButton("🗑 حذف ملف")],
        [KeyboardButton("🔄 إعادة تشغيل"), KeyboardButton("🔙 المجلد السابق")],
        [KeyboardButton("الرجوع لإدارة البوت")]
    ], resize_keyboard=True)

def admin_users_menu():
    return ReplyKeyboardMarkup([
        [KeyboardButton("إدارة تنصيب عضو"), KeyboardButton("حذف تنصيب عضو")],
        [KeyboardButton("إيقاف مؤقت لعضو"), KeyboardButton("تشغيل لعضو")],
        [KeyboardButton("فك حظر"), KeyboardButton("زيادة تنصيب")],
        [KeyboardButton("رجوع")]
    ], resize_keyboard=True)

# ================= التوجيهات الأساسية =================

@app.on_message(filters.command("start") & filters.private)
async def start_command(client: Client, message: Message):
    db = load_db()
    if str(message.from_user.id) in db.get("banned", []):
        return await message.reply("أنت محظور من الاستخدام.")
    user_states[message.from_user.id] = {"step": None}
    await message.reply("أهلاً بك. اختر من القائمة أدناه:", reply_markup=main_menu(message.from_user.id))

@app.on_message(filters.text & filters.private)
async def handle_texts(client: Client, message: Message):
    user_id = message.from_user.id
    text = message.text
    db = load_db()

    if user_id not in user_states or user_states[user_id] is None:
        user_states[user_id] = {"step": None}
    state = user_states[user_id]
    step = state.get("step")

    # ========== أزرار الرجوع ==========
    if text == "رجوع":
        user_states[user_id] = {"step": None, "target_id": None}
        return await message.reply("تم الرجوع للرئيسية.", reply_markup=main_menu(user_id))

    if text == "الرجوع لإدارة البوت":
        state["step"] = None
        return await message.reply("تم الرجوع لقائمة الإدارة.", reply_markup=manage_menu())

    # ========== استقبال الإدخالات ==========
    if step == "WAITING_INPUT":
        target_id = state.get("target_id", user_id)
        slot = state.get("selected_slot")
        process_key = f"{target_id}_{slot}"
        cleaned = text.replace(" ", "") if ":" in text else text.translate(str.maketrans("", "", " +-()"))
        if process_key in running_bots and running_bots[process_key].poll() is None:
            try:
                running_bots[process_key].stdin.write(f"{cleaned}\n".encode('utf-8'))
                running_bots[process_key].stdin.flush()
                await message.reply("✅ تم الإدخال بنجاح.")
            except Exception as e:
                await message.reply(f"❌ خطأ أثناء الإدخال: {e}")
        else:
            await message.reply("⚠️ عذراً، البوت لا يعمل لكي يستقبل بيانات.")
        state["step"] = None
        return

    # ========== إدارة الملفات (النصوص) ==========
    if step == "WAITING_FOLDER_NAME":
        target_path = os.path.join(state["current_dir"], text)
        if os.path.isdir(target_path):
            state["current_dir"] = target_path
            await message.reply(f"✅ تم الدخول للمجلد: `{text}`\nاضغط 'عرض الملفات' لرؤية المحتوى.")
        else:
            await message.reply("❌ المجلد غير موجود. تأكد من الاسم.")
        state["step"] = None
        return

    if step == "WAITING_DELETE_FILE_NAME":
        target_path = os.path.join(state["current_dir"], text)
        if os.path.exists(target_path):
            try:
                if os.path.isdir(target_path):
                    shutil.rmtree(target_path)
                else:
                    os.remove(target_path)
                await message.reply("✅ تم الحذف بنجاح.")
            except Exception as e:
                await message.reply(f"❌ حدث خطأ أثناء الحذف: {e}")
        else:
            await message.reply("❌ الملف/المجلد غير موجود.")
        state["step"] = None
        return

    # ========== خطوات الحذف والإدارة ==========
    if step == "WAITING_SLOT_DELETE" and text.isdigit():
        slot = int(text)
        slot_dir = f"hostings/{user_id}/slot_{slot}"
        if os.path.exists(slot_dir):
            shutil.rmtree(slot_dir, ignore_errors=True)
            process_key = f"{user_id}_{slot}"
            if process_key in running_bots:
                try:
                    running_bots[process_key].terminate()
                except:
                    pass
                del running_bots[process_key]
            await message.reply("✅ تم حذف التنصيب بنجاح.")
        else:
            await message.reply("❌ التنصيب غير موجود.")
        state["step"] = None
        return

    if step == "WAITING_SLOT_MANAGE" and text.isdigit():
        slot = int(text)
        slot_dir = f"hostings/{user_id}/slot_{slot}"
        if os.path.exists(slot_dir):
            state["selected_slot"] = slot
            state["target_id"] = user_id
            state["step"] = None
            return await message.reply(f"✅ تم الدخول لإدارة التنصيب رقم ({slot}). اختر الإجراء:", reply_markup=manage_menu())
        else:
            await message.reply("❌ التنصيب غير موجود.")
            state["step"] = None
            return

    # ========== خطوات المطور ==========
    if step == "ADMIN_WAITING_USER_ID" and text.isdigit():
        target_id = int(text)
        slots = get_active_slots(target_id)
        if not slots:
            state["step"] = None
            return await message.reply("العضو ليس لديه تنصيبات.")
        elif len(slots) == 1:
            await execute_admin_user_action(message, state["action"], target_id, slots[0])
            state["step"] = None
            return
        else:
            state["step"] = "ADMIN_WAITING_USER_SLOT"
            state["target"] = target_id
            return await message.reply("العضو لديه أكثر من تنصيب، أدخل الرقم الذي تريد التحكم به:")

    if step == "ADMIN_WAITING_USER_SLOT" and text.isdigit():
        await execute_admin_user_action(message, state["action"], state["target"], int(text))
        state["step"] = None
        return

    if step == "ADMIN_UNBAN_ID" and text.isdigit():
        uid = str(text)
        if uid in db["banned"]:
            db["banned"].remove(uid)
            save_db(db)
            await message.reply("✅ تم فك الحظر.")
        else:
            await message.reply("❌ هذا المستخدم غير محظور.")
        state["step"] = None
        return

    if step == "ADMIN_ADD_LIMIT" and text.isdigit():
        uid = str(text)
        db["users"][uid] = db["users"].get(uid, 2) + 1
        save_db(db)
        await message.reply(f"✅ تم تزويد عدد التنصيبات المسموحة للعضوية `{uid}` إلى {db['users'][uid]}.")
        state["step"] = None
        return

    # ========== إدارة VIP ==========
    if step == "ADMIN_VIP_ADD_ID" and text.isdigit():
        state["vip_user_id"] = int(text)
        state["step"] = "ADMIN_VIP_ADD_TIME"
        return await message.reply("أدخل مدة الـ VIP بالأيام (رقم فقط):")

    if step == "ADMIN_VIP_ADD_TIME" and text.isdigit():
        days = int(text)
        uid = str(state["vip_user_id"])
        expiry = time.time() + days * 86400
        db["vip"][uid] = expiry
        save_db(db)
        state["step"] = None
        await message.reply(f"✅ تم رفع العضو `{uid}` إلى VIP لمدة {days} يوم.")
        return

    if step == "ADMIN_VIP_REMOVE_ID" and text.isdigit():
        uid = str(text)
        if uid in db.get("vip", {}):
            del db["vip"][uid]
            save_db(db)
            await message.reply(f"✅ تم تنزيل العضو `{uid}` من VIP.")
        else:
            await message.reply("❌ هذا العضو ليس VIP.")
        state["step"] = None
        return

    # ========== الأزرار الرئيسية ==========

    if text == "تنصيب بوت":
        await check_disk_space(client)
        if db.get("locked", False) and user_id != ADMIN_ID:
            btn = InlineKeyboardMarkup([[InlineKeyboardButton("المطور", url=f"tg://user?id={ADMIN_ID}")]])
            return await message.reply("🔒 عذراً، تم قفل التنصيب حالياً بواسطة المطور. يرجى مراسلته.", reply_markup=btn)

        limit = get_user_limit(user_id)
        slots = get_active_slots(user_id)
        if len(slots) >= limit:
            return await message.reply("❌ وصلت للحد الأقصى للتنصيبات المسموح بها.")

        available_slot = next((i for i in range(1, limit + 2) if i not in slots), 1)
        state["step"] = "WAITING_FOR_ZIP"
        state["slot"] = available_slot
        return await message.reply("أرسل ملف البوت (.zip أو .py فقط) الآن:")

    elif text == "حذف تنصيب":
        slots = get_active_slots(user_id)
        if not slots:
            return await message.reply("لا يوجد لديك تنصيبات لحذفها.")
        if len(slots) == 1:
            slot = slots[0]
            process_key = f"{user_id}_{slot}"
            if process_key in running_bots:
                try:
                    running_bots[process_key].terminate()
                except:
                    pass
                del running_bots[process_key]
            shutil.rmtree(f"hostings/{user_id}/slot_{slot}", ignore_errors=True)
            return await message.reply("✅ تم حذف التنصيب بنجاح.")
        else:
            state["step"] = "WAITING_SLOT_DELETE"
            return await message.reply("لديك أكثر من تنصيب، أدخل الرقم الذي تريد حذفه:")

    elif text in ["قسم الإدارة", "إدارة بوتك"]:
        state["target_id"] = user_id
        slots = get_active_slots(user_id)
        if not slots:
            return await message.reply("لا يوجد تنصيبات حالياً لإدارتها.")
        if len(slots) == 1:
            state["selected_slot"] = slots[0]
            return await message.reply(f"تم اختيار التنصيب التلقائي ({slots[0]}). اختر الإجراء:", reply_markup=manage_menu())
        else:
            state["step"] = "WAITING_SLOT_MANAGE"
            return await message.reply("أدخل رقم التنصيب الذي تريد إدارته:")

    # ========== أزرار المطور ==========

    elif text == "المنصبين" and user_id == ADMIN_ID:
        if not os.path.exists("hostings") or not os.listdir("hostings"):
            return await message.reply("لا يوجد أي تنصيبات حالياً.")
        msg = "📋 **قائمة المنصبين:**\n\n"
        count = 1
        for uid in os.listdir("hostings"):
            user_path = os.path.join("hostings", uid)
            if os.path.isdir(user_path):
                for slot_dir in os.listdir(user_path):
                    if slot_dir.startswith("slot_"):
                        slot_num = slot_dir.split("_")[1]
                        bot_dir = f"{user_path}/{slot_dir}/bot"
                        script_path = find_main_script(bot_dir)
                        file_name = os.path.basename(script_path) if script_path else "غير معروف"
                        msg += f"**{count}-**\n"
                        msg += f"👤 **الآيدي:** `{uid}`\n"
                        msg += f"📦 **رقم التنصيب:** `{slot_num}`\n"
                        msg += f"📄 **الملف الرئيسي:** `{file_name}`\n"
                        msg += "──────────────\n"
                        count += 1
        if count == 1:
            return await message.reply("لا يوجد أي تنصيبات حالياً.")
        return await message.reply(msg)

    elif text == "جلب نسخة احتياطية" and user_id == ADMIN_ID:
        msg = await message.reply("⏳ جاري تحضير النسخة الاحتياطية...")
        backup_name = "Backup.zip"
        try:
            with zipfile.ZipFile(backup_name, 'w', zipfile.ZIP_DEFLATED) as zipf:
                if os.path.exists("database.json"):
                    zipf.write("database.json")
                if os.path.exists("hostings"):
                    for root, _, files in os.walk("hostings"):
                        for file in files:
                            zipf.write(os.path.join(root, file))
            await message.reply_document(backup_name, caption="📦 النسخة الاحتياطية الخاصة بك جاهزة.")
            os.remove(backup_name)
            await msg.delete()
        except Exception as e:
            await msg.edit_text(f"❌ حدث خطأ أثناء تجهيز النسخة: {e}")

    elif text == "رفع نسخة احتياطية" and user_id == ADMIN_ID:
        state["step"] = "ADMIN_WAITING_BACKUP"
        return await message.reply("أرسل ملف النسخة الاحتياطية (`.zip`) الآن:\n⚠️ **تحذير:** رفع النسخة سيقوم بإيقاف البوتات الشغالة واستبدال الملفات ثم إعادة تشغيلهم تلقائياً.")

    elif text == "إدارة بوتات الأعضاء" and user_id == ADMIN_ID:
        return await message.reply("إدارة الأعضاء:", reply_markup=admin_users_menu())

    elif text == "الإحصائيات والتقرير" and user_id == ADMIN_ID:
        total_users = len(db["users"])
        active_installations = 0
        if os.path.exists("hostings"):
            for uid in os.listdir("hostings"):
                user_path = os.path.join("hostings", uid)
                if os.path.isdir(user_path):
                    for slot_dir in os.listdir(user_path):
                        if slot_dir.startswith("slot_"):
                            active_installations += 1
        total, used, free = shutil.disk_usage("/")
        disk_percent = (used / total) * 100
        report = (
            "📊 **تقرير الإحصائيات المفصل:**\n\n"
            f"👥 **المستخدمين المسجلين:** `{total_users}`\n"
            f"🤖 **إجمالي التنصيبات:** `{active_installations}`\n"
            f"⚡ **البوتات الشغالة حالياً:** `{len(running_bots)}`\n"
            f"💾 **مساحة السيرفر:** `{disk_percent:.1f}%`"
        )
        return await message.reply(report)

    elif text in ["إدارة تنصيب عضو", "حذف تنصيب عضو", "إيقاف مؤقت لعضو", "تشغيل لعضو"] and user_id == ADMIN_ID:
        state["step"] = "ADMIN_WAITING_USER_ID"
        state["action"] = text
        return await message.reply("أدخل الآيدي (ID) الخاص بالعضو:")

    elif text == "فك حظر" and user_id == ADMIN_ID:
        state["step"] = "ADMIN_UNBAN_ID"
        return await message.reply("أدخل الآيدي لفك الحظر:")

    elif text == "زيادة تنصيب" and user_id == ADMIN_ID:
        state["step"] = "ADMIN_ADD_LIMIT"
        return await message.reply("أدخل الآيدي لزيادة الحد:")

    elif text == "قفل التنصيب" and user_id == ADMIN_ID:
        db["locked"] = True
        save_db(db)
        return await message.reply("🔒 تم قفل التنصيب.")

    elif text == "تشغيل التنصيب" and user_id == ADMIN_ID:
        db["locked"] = False
        save_db(db)
        return await message.reply("🔓 تم فتح التنصيب.")

    # ========== إدارة VIP ==========
    elif text == "رفع عضو VIP" and user_id == ADMIN_ID:
        state["step"] = "ADMIN_VIP_ADD_ID"
        return await message.reply("أدخل آيدي العضو لرفعه VIP:")

    elif text == "تنزيل عضو VIP" and user_id == ADMIN_ID:
        state["step"] = "ADMIN_VIP_REMOVE_ID"
        return await message.reply("أدخل آيدي العضو لتنزيله من VIP:")

    elif text == "عرض الأعضاء VIP" and user_id == ADMIN_ID:
        vip_data = db.get("vip", {})
        if not vip_data:
            return await message.reply("لا يوجد أعضاء VIP حالياً.")
        msg = "🌟 **قائمة الأعضاء VIP:**\n\n"
        for uid, expiry in vip_data.items():
            if expiry > time.time():
                remaining = int((expiry - time.time()) / 86400)  # أيام
                msg += f"👤 **العضو:** `{uid}`\n⏳ **متبقي:** `{remaining}` يوم\n──────────────\n"
            else:
                # انتهت صلاحيته، سيتم حذفه تلقائياً عند المحاولة
                pass
        if msg == "🌟 **قائمة الأعضاء VIP:**\n\n":
            return await message.reply("لا يوجد أعضاء VIP صالحين حالياً.")
        return await message.reply(msg)

    # ========== أزرار إدارة البوت والملفات ==========

    elif text in ["سجل البوت", "حالة البوت", "إيقاف مؤقت", "تشغيل البوت", "⌨️ إدخال بيانات", "📂 إدارة الملفات", "🔄 إعادة تشغيل"]:
        slot = state.get("selected_slot")
        target_id = state.get("target_id", user_id)
        if not slot:
            return await message.reply("يرجى اختيار التنصيب أولاً.", reply_markup=main_menu(user_id))

        process_key = f"{target_id}_{slot}"
        user_dir = f"hostings/{target_id}/slot_{slot}"
        bot_dir = f"{user_dir}/bot"

        if text == "سجل البوت":
            log_path = f"{user_dir}/log.txt"
            if os.path.exists(log_path):
                with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                    log_text = "".join(f.readlines()[-50:])
                return await message.reply(f"**سجل التنصيب:**\n```\n{log_text[-4000:]}\n```")
            else:
                return await message.reply("لا يوجد سجل حتى الآن.")

        elif text == "حالة البوت":
            if process_key in running_bots and running_bots[process_key].poll() is None:
                return await message.reply("الحالة: يعمل 🟢")
            else:
                return await message.reply("الحالة: متوقف ⚪")

        elif text == "إيقاف مؤقت":
            if process_key in running_bots:
                try:
                    running_bots[process_key].terminate()
                except:
                    pass
                del running_bots[process_key]
                return await message.reply("تم الإيقاف المؤقت بنجاح.")
            else:
                return await message.reply("البوت متوقف بالفعل.")

        elif text == "تشغيل البوت":
            script_path = find_main_script(bot_dir)
            if script_path:
                auto_install_requirements(bot_dir, script_path)
                p = subprocess.Popen(
                    ["python3", os.path.basename(script_path)],
                    cwd=os.path.dirname(script_path),
                    stdin=subprocess.PIPE,
                    stdout=open(f"{user_dir}/log.txt", "a"),
                    stderr=subprocess.STDOUT
                )
                running_bots[process_key] = p
                return await message.reply("تم تشغيل البوت بنجاح.")
            else:
                return await message.reply("لم يتم العثور على ملف py للتشغيل.")

        elif text == "🔄 إعادة تشغيل":
            if process_key in running_bots:
                try:
                    running_bots[process_key].terminate()
                except:
                    pass
                del running_bots[process_key]
            script_path = find_main_script(bot_dir)
            if script_path:
                auto_install_requirements(bot_dir, script_path)
                p = subprocess.Popen(
                    ["python3", os.path.basename(script_path)],
                    cwd=os.path.dirname(script_path),
                    stdin=subprocess.PIPE,
                    stdout=open(f"{user_dir}/log.txt", "a"),
                    stderr=subprocess.STDOUT
                )
                running_bots[process_key] = p
                return await message.reply("✅ تم إعادة تشغيل البوت بنجاح.")
            else:
                return await message.reply("❌ لم يتم العثور على ملف التشغيل.")

        elif text == "⌨️ إدخال بيانات":
            if process_key in running_bots and running_bots[process_key].poll() is None:
                state["step"] = "WAITING_INPUT"
                return await message.reply("أدخل القيمة الآن:")
            else:
                return await message.reply("البوت متوقف، لا يمكن إرسال بيانات له.")

        elif text == "📂 إدارة الملفات":
            state["current_dir"] = bot_dir
            return await message.reply("أهلاً بك في قسم إدارة الملفات:", reply_markup=file_manage_menu())

    # ========== أزرار إدارة الملفات ==========

    elif text in ["📄 عرض الملفات", "📁 دخول مجلد", "➕ إضافة ملف", "🔄 تبديل ملف", "🗑 حذف ملف", "🔙 المجلد السابق"]:
        current_dir = state.get("current_dir")
        if not current_dir or not os.path.exists(current_dir):
            return await message.reply("الرجاء الدخول لإدارة الملفات أولاً.", reply_markup=manage_menu())

        target_id = state.get("target_id", user_id)
        slot = state.get("selected_slot")
        base_bot_dir = os.path.abspath(f"hostings/{target_id}/slot_{slot}/bot")

        if text == "📄 عرض الملفات":
            items = os.listdir(current_dir)
            if not items:
                return await message.reply("المجلد فارغ.")
            msg = "**الملفات والمجلدات:**\n\n"
            for item in sorted(items):
                full = os.path.join(current_dir, item)
                if os.path.isdir(full):
                    msg += f"📁 `{item}`\n"
                else:
                    msg += f"📄 `{item}`\n"
            return await message.reply(msg)

        elif text == "📁 دخول مجلد":
            state["step"] = "WAITING_FOLDER_NAME"
            return await message.reply("أدخل اسم المجلد الذي تريد الدخول إليه بالضبط:")

        elif text == "🔙 المجلد السابق":
            abs_current = os.path.abspath(current_dir)
            if abs_current == base_bot_dir:
                return await message.reply("أنت في المجلد الرئيسي (الأساسي) للبوت، لا يمكن الرجوع أكثر.")
            state["current_dir"] = os.path.dirname(abs_current)
            return await message.reply("تم الرجوع للمجلد السابق. اضغط 'عرض الملفات'.")

        elif text == "🗑 حذف ملف":
            state["step"] = "WAITING_DELETE_FILE_NAME"
            return await message.reply("أدخل اسم الملف أو المجلد الذي تريد حذفه (بما في ذلك الصيغة):")

        elif text == "➕ إضافة ملف":
            state["step"] = "WAITING_ADD_FILE"
            return await message.reply("أرسل الملف الجديد الآن.\nسيتم حفظه بنفس اسمه في المجلد الحالي.")

        elif text == "🔄 تبديل ملف":
            state["step"] = "WAITING_REPLACE_FILE"
            return await message.reply("أرسل الملف الجديد الآن.\n⚠️ **ملاحظة:** يجب أن يكون اسم الملف المرسل هو نفس اسم الملف الموجود في المجلد ليتم استبداله.")

    # إذا لم يتطابق أي شرط
    await message.reply("أمر غير معروف، استخدم الأزرار من القائمة.", reply_markup=main_menu(user_id))


async def execute_admin_user_action(message, action, target_id, slot):
    process_key = f"{target_id}_{slot}"
    user_dir = f"hostings/{target_id}/slot_{slot}"

    if action == "إدارة تنصيب عضو":
        user_states[message.from_user.id]["target_id"] = target_id
        user_states[message.from_user.id]["selected_slot"] = slot
        await message.reply(f"تم الدخول بنجاح لإدارة التنصيب ({slot}) للعضو ({target_id}).", reply_markup=manage_menu())

    elif action == "حذف تنصيب عضو":
        if process_key in running_bots:
            try:
                running_bots[process_key].terminate()
            except:
                pass
            del running_bots[process_key]
        shutil.rmtree(user_dir, ignore_errors=True)
        await message.reply(f"تم حذف التنصيب ({slot}) للعضو بنجاح.")

    elif action == "إيقاف مؤقت لعضو":
        if process_key in running_bots:
            try:
                running_bots[process_key].terminate()
            except:
                pass
            del running_bots[process_key]
            await message.reply(f"تم إيقاف التنصيب ({slot}) للعضو.")
        else:
            await message.reply("التنصيب متوقف بالفعل.")

    elif action == "تشغيل لعضو":
        script_path = find_main_script(f"{user_dir}/bot")
        if script_path:
            auto_install_requirements(f"{user_dir}/bot", script_path)
            p = subprocess.Popen(
                ["python3", os.path.basename(script_path)],
                cwd=os.path.dirname(script_path),
                stdin=subprocess.PIPE,
                stdout=open(f"{user_dir}/log.txt", "a"),
                stderr=subprocess.STDOUT
            )
            running_bots[process_key] = p
            await message.reply(f"تم تشغيل التنصيب ({slot}) للعضو.")
        else:
            await message.reply("لم يتم العثور على ملف تشغيل للبوت.")


# ================= التعامل مع الملفات =================

@app.on_message(filters.document & filters.private)
async def handle_docs(client: Client, message: Message):
    user_id = message.from_user.id
    state = user_states.get(user_id, {})
    step = state.get("step")
    file_name = message.document.file_name

    # --- استعادة نسخة احتياطية (للمطور فقط) ---
    if step == "ADMIN_WAITING_BACKUP" and user_id == ADMIN_ID:
        if not file_name.endswith(".zip"):
            return await message.reply("❌ يرجى إرسال ملف بصيغة .zip فقط.")

        msg = await message.reply("⏳ جاري رفع واستخراج النسخة الاحتياطية...")

        # إيقاف جميع البوتات
        for key, p in list(running_bots.items()):
            try:
                p.terminate()
            except:
                pass
        running_bots.clear()

        downloaded_path = await message.download()

        try:
            with zipfile.ZipFile(downloaded_path, 'r') as zip_ref:
                zip_ref.extractall(".")
            os.remove(downloaded_path)

            # إعادة تشغيل البوتات الموجودة
            restarted_count = 0
            if os.path.exists("hostings"):
                for uid in os.listdir("hostings"):
                    user_path = os.path.join("hostings", uid)
                    if os.path.isdir(user_path):
                        for slot_dir in os.listdir(user_path):
                            if slot_dir.startswith("slot_"):
                                slot_num = slot_dir.split("_")[1]
                                bot_dir = f"{user_path}/{slot_dir}/bot"
                                script_path = find_main_script(bot_dir)
                                if script_path:
                                    auto_install_requirements(bot_dir, script_path)
                                    p = subprocess.Popen(
                                        ["python3", os.path.basename(script_path)],
                                        cwd=os.path.dirname(script_path),
                                        stdin=subprocess.PIPE,
                                        stdout=open(f"{user_path}/{slot_dir}/log.txt", "a"),
                                        stderr=subprocess.STDOUT
                                    )
                                    running_bots[f"{uid}_{slot_num}"] = p
                                    restarted_count += 1

            user_states[user_id]["step"] = None
            await msg.edit_text(f"✅ تم استعادة النسخة الاحتياطية بنجاح!\n🤖 تم إعادة تشغيل {restarted_count} بوت تلقائياً.")
        except Exception as e:
            await msg.edit_text(f"❌ حدث خطأ أثناء الاستخراج: {e}")
        return

    # --- إضافة ملف جديد ---
    if step == "WAITING_ADD_FILE":
        current_dir = state.get("current_dir")
        if not current_dir or not os.path.exists(current_dir):
            state["step"] = None
            return await message.reply("❌ حدث خطأ، يرجى الدخول للمجلد مرة أخرى.")

        target_path = os.path.join(current_dir, file_name)
        msg = await message.reply(f"⏳ جاري حفظ الملف `{file_name}`...")

        downloaded = await message.download()
        shutil.move(downloaded, target_path)

        state["step"] = None
        return await msg.edit_text(f"✅ تم إضافة الملف `{file_name}` بنجاح.\nاضغط '🔄 إعادة تشغيل' لتطبيق التغييرات إذا لزم الأمر.")

    # --- تبديل ملف ---
    if step == "WAITING_REPLACE_FILE":
        current_dir = state.get("current_dir")
        target_path = os.path.join(current_dir, file_name)

        if not os.path.exists(target_path) or not os.path.isfile(target_path):
            state["step"] = None
            return await message.reply(f"❌ خطأ: لا يوجد ملف باسم `{file_name}` في المجلد الحالي لتبديله. يجب أن يحمل نفس الاسم بالضبط.")

        os.remove(target_path)
        downloaded = await message.download()
        shutil.move(downloaded, target_path)

        state["step"] = None
        return await message.reply(f"✅ تم تبديل وتحديث الملف `{file_name}` بنجاح.\nلا تنسَ عمل '🔄 إعادة تشغيل' للبوت.")

    # --- تنصيب بوت جديد ---
    if step == "WAITING_FOR_ZIP":
        if not (file_name.endswith(".zip") or file_name.endswith(".py")):
            return await message.reply("❌ غير مسموح. يتم قبول ملفات `.zip` أو `.py` فقط.\nأي ملفات أخرى تم رفضها للحفاظ على المساحة.")

        slot = state.get("slot")
        if not slot:
            return await message.reply("❌ حدث خطأ في الجلسة، أعد المحاولة من البداية.")

        msg = await message.reply("جاري سحب الملفات والتحميل...")

        bot_dir = f"hostings/{user_id}/slot_{slot}/bot"
        os.makedirs(bot_dir, exist_ok=True)

        downloaded = await message.download()

        if file_name.endswith(".zip"):
            try:
                normalize_zip_extraction(downloaded, bot_dir)
            except Exception as e:
                shutil.rmtree(f"hostings/{user_id}/slot_{slot}", ignore_errors=True)
                state["step"] = None
                return await msg.edit_text(f"❌ فشل استخراج الملف المضغوط: {e}")
            os.remove(downloaded)
        else:
            shutil.move(downloaded, f"{bot_dir}/{file_name}")

        script_path = find_main_script(bot_dir)
        if not script_path:
            shutil.rmtree(f"hostings/{user_id}/slot_{slot}", ignore_errors=True)
            state["step"] = None
            return await msg.edit_text("❌ فشل: الملف المرفوع لا يحتوي على ملف بايثون (.py).\nتم مسح الملفات فوراً من السيرفر لتوفير المساحة.")

        script_name = os.path.basename(script_path)
        script_dir = os.path.dirname(script_path)

        auto_install_requirements(bot_dir, script_path)

        log_file = open(f"hostings/{user_id}/slot_{slot}/log.txt", "w")
        process = subprocess.Popen(
            ["python3", script_name],
            cwd=script_dir,
            stdin=subprocess.PIPE,
            stdout=log_file,
            stderr=subprocess.STDOUT
        )
        running_bots[f"{user_id}_{slot}"] = process

        await msg.edit_text(f"✅ تم تنصيب البوت بنجاح. (رقم التنصيب: {slot})", reply_markup=main_menu(user_id))

        admin_report = (
            "🔔 **إشعار تنصيب جديد!**\n\n"
            f"👤 **المستخدم:** [{message.from_user.first_name}](tg://user?id={user_id})\n"
            f"🆔 **الآيدي:** `{user_id}`\n"
            f"📦 **رقم التنصيب:** `{slot}`\n"
            f"📄 **اسم الملف:** `{file_name}`\n"
            f"✅ **الحالة:** تم التنصيب والتشغيل بنجاح."
        )
        try:
            await client.send_message(ADMIN_ID, admin_report)
        except:
            pass

        state["step"] = None
        return

    # إذا لم يتطابق أي شرط
    await message.reply("❌ هذا الملف غير مطلوب في الوقت الحالي، استخدم الأزرار المناسبة.")


app.run()