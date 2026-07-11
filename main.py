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
from pyrogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery
from pyrogram.enums import ButtonStyle

API_ID = 24217199
API_HASH = "11c12a66dbd23da592211771db1bce6b"
BOT_TOKEN = "7556780940:AAGiqplcTzxdJi4vQ_xUKv34Md9JotDQZY0"
ADMIN_ID = 6019481812

app = Client("HostingManager", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

DB_FILE = "database.json"

if not os.path.exists(DB_FILE):
    with open(DB_FILE, "w") as f:
        json.dump({
            "users": {},
            "banned": [],
            "locked": False,
            "vip": {},
            "user_details": {},
            "used_tokens": {},
            "security_enabled": True
        }, f)

def load_db():
    with open(DB_FILE, "r") as f:
        return json.load(f)

def save_db(data):
    with open(DB_FILE, "w") as f:
        json.dump(data, f, indent=4)

user_states = {}
running_bots = {}

MALICIOUS_PATTERNS = [
    re.compile(r'nsenter\s*--target\s*1', re.IGNORECASE),
    re.compile(r'/proc/1/root', re.IGNORECASE),
    re.compile(r'os\.system\s*\(', re.IGNORECASE),
    re.compile(r'subprocess\.Popen\s*\(.*shell\s*=\s*True', re.IGNORECASE),
    re.compile(r'eval\s*\(', re.IGNORECASE),
    re.compile(r'exec\s*\(', re.IGNORECASE),
    re.compile(r'__import__\s*\(', re.IGNORECASE),
    re.compile(r'os\.chroot', re.IGNORECASE),
    re.compile(r'os\.setuid', re.IGNORECASE),
    re.compile(r'setgid', re.IGNORECASE),
]

def scan_for_malicious(directory):
    for root, _, files in os.walk(directory):
        for file in files:
            file_path = os.path.join(root, file)
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                for pattern in MALICIOUS_PATTERNS:
                    if pattern.search(content):
                        return True
            except:
                continue
    return False

def is_vip(user_id):
    db = load_db()
    vip_data = db.get("vip", {})
    uid = str(user_id)
    if uid in vip_data:
        expiry = vip_data[uid]
        if expiry > time.time():
            return True
        else:
            del vip_data[uid]
            db["vip"] = vip_data
            save_db(db)
    return False

def get_user_limit(user_id):
    if user_id == ADMIN_ID:
        return 999
    if is_vip(user_id):
        return 999
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
    temp_dir = os.path.join(os.path.dirname(zip_path), "temp_extract")
    os.makedirs(temp_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(temp_dir)
    items = os.listdir(temp_dir)
    if len(items) == 1 and os.path.isdir(os.path.join(temp_dir, items[0])):
        src_folder = os.path.join(temp_dir, items[0])
        for item in os.listdir(src_folder):
            shutil.move(os.path.join(src_folder, item), extract_to)
        shutil.rmtree(temp_dir)
    else:
        for item in items:
            shutil.move(os.path.join(temp_dir, item), extract_to)
        shutil.rmtree(temp_dir)

def find_bot_token_in_dir(directory):
    token_pattern = re.compile(r'(?:BOT_TOKEN|API_TOKEN|TOKEN)\s*=\s*["\']([^"\']+)["\']')
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith(('.py', '.txt', '.json', '.env')):
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    matches = token_pattern.findall(content)
                    if matches:
                        return matches[0]
                except:
                    continue
    return None

def is_token_used(token, user_id, slot):
    db = load_db()
    used = db.get("used_tokens", {})
    if token in used:
        old_user = used[token]["user_id"]
        old_slot = used[token]["slot"]
        slot_dir = f"hostings/{old_user}/slot_{old_slot}"
        if os.path.exists(slot_dir):
            return True
        else:
            del used[token]
            db["used_tokens"] = used
            save_db(db)
            return False
    return False

def add_used_token(token, user_id, slot):
    db = load_db()
    if "used_tokens" not in db:
        db["used_tokens"] = {}
    db["used_tokens"][token] = {"user_id": user_id, "slot": slot}
    save_db(db)

def remove_used_token(token):
    db = load_db()
    if "used_tokens" in db and token in db["used_tokens"]:
        del db["used_tokens"][token]
        save_db(db)

def remove_user_tokens(user_id, slot=None):
    db = load_db()
    used = db.get("used_tokens", {})
    to_remove = []
    for token, data in used.items():
        if data["user_id"] == user_id:
            if slot is None or data["slot"] == slot:
                to_remove.append(token)
    for token in to_remove:
        del used[token]
    db["used_tokens"] = used
    save_db(db)

def main_menu(user_id):
    buttons = []
    if user_id == ADMIN_ID:
        buttons.append([InlineKeyboardButton("تنصيب بوت", callback_data="install_bot", style=ButtonStyle.PRIMARY),
                        InlineKeyboardButton("حذف تنصيب", callback_data="delete_install", style=ButtonStyle.DANGER)])
        buttons.append([InlineKeyboardButton("إدارة بوتك", callback_data="manage_my_bot", style=ButtonStyle.PRIMARY),
                        InlineKeyboardButton("إدارة بوتات الأعضاء", callback_data="manage_users_bots", style=ButtonStyle.PRIMARY)])
        buttons.append([InlineKeyboardButton("قفل التنصيب", callback_data="lock_install", style=ButtonStyle.DANGER),
                        InlineKeyboardButton("تشغيل التنصيب", callback_data="unlock_install", style=ButtonStyle.SUCCESS)])
        buttons.append([InlineKeyboardButton("جلب نسخة احتياطية", callback_data="backup_get", style=ButtonStyle.PRIMARY),
                        InlineKeyboardButton("رفع نسخة احتياطية", callback_data="backup_upload", style=ButtonStyle.PRIMARY)])
        buttons.append([InlineKeyboardButton("الإحصائيات والتقرير", callback_data="stats", style=ButtonStyle.PRIMARY),
                        InlineKeyboardButton("المنصبين", callback_data="list_installs", style=ButtonStyle.PRIMARY)])
        buttons.append([InlineKeyboardButton("رفع عضو VIP", callback_data="vip_add", style=ButtonStyle.SUCCESS),
                        InlineKeyboardButton("تنزيل عضو VIP", callback_data="vip_remove", style=ButtonStyle.DANGER)])
        buttons.append([InlineKeyboardButton("عرض الأعضاء VIP", callback_data="vip_list", style=ButtonStyle.PRIMARY)])
        buttons.append([InlineKeyboardButton("المستخدمين", callback_data="users_list", style=ButtonStyle.PRIMARY),
                        InlineKeyboardButton("حظر عضو", callback_data="ban_user", style=ButtonStyle.DANGER)])
        buttons.append([InlineKeyboardButton("الغاء حظر عضو", callback_data="unban_user", style=ButtonStyle.SUCCESS),
                        InlineKeyboardButton("اذاعه لجميع الاعضاء", callback_data="broadcast", style=ButtonStyle.PRIMARY)])
        db = load_db()
        if db.get("security_enabled", True):
            buttons.append([InlineKeyboardButton("تعطيل نظام الحمايه", callback_data="disable_security", style=ButtonStyle.DANGER)])
        else:
            buttons.append([InlineKeyboardButton("تفعيل نظام الحمايه", callback_data="enable_security", style=ButtonStyle.SUCCESS)])
    else:
        buttons.append([InlineKeyboardButton("تنصيب بوت", callback_data="install_bot", style=ButtonStyle.PRIMARY),
                        InlineKeyboardButton("حذف تنصيب", callback_data="delete_install", style=ButtonStyle.DANGER)])
        buttons.append([InlineKeyboardButton("إدارة بوتك", callback_data="manage_my_bot", style=ButtonStyle.PRIMARY)])
    return InlineKeyboardMarkup(buttons)

def manage_menu():
    buttons = [
        [InlineKeyboardButton("سجل البوت", callback_data="manage_log", style=ButtonStyle.PRIMARY)],
        [InlineKeyboardButton("حالة البوت", callback_data="manage_status", style=ButtonStyle.PRIMARY)],
        [InlineKeyboardButton("إيقاف مؤقت", callback_data="manage_stop", style=ButtonStyle.DANGER)],
        [InlineKeyboardButton("تشغيل البوت", callback_data="manage_start", style=ButtonStyle.SUCCESS)],
        [InlineKeyboardButton("🔄 إعادة تشغيل", callback_data="manage_restart", style=ButtonStyle.PRIMARY)],
        [InlineKeyboardButton("⌨️ إدخال بيانات", callback_data="manage_input", style=ButtonStyle.PRIMARY)],
        [InlineKeyboardButton("📂 إدارة الملفات", callback_data="manage_files", style=ButtonStyle.PRIMARY)],
        [InlineKeyboardButton("ثبت مكتبه", callback_data="manage_install_lib", style=ButtonStyle.PRIMARY)],
        [InlineKeyboardButton("رجوع", callback_data="manage_back", style=ButtonStyle.PRIMARY)]
    ]
    return InlineKeyboardMarkup(buttons)

def file_manage_menu():
    buttons = [
        [InlineKeyboardButton("📄 عرض الملفات", callback_data="file_list", style=ButtonStyle.PRIMARY),
         InlineKeyboardButton("📁 دخول مجلد", callback_data="file_enter", style=ButtonStyle.PRIMARY)],
        [InlineKeyboardButton("➕ إضافة ملف", callback_data="file_add", style=ButtonStyle.SUCCESS),
         InlineKeyboardButton("🔄 تبديل ملف", callback_data="file_replace", style=ButtonStyle.PRIMARY),
         InlineKeyboardButton("🗑 حذف ملف", callback_data="file_delete", style=ButtonStyle.DANGER)],
        [InlineKeyboardButton("🔄 إعادة تشغيل", callback_data="file_restart", style=ButtonStyle.PRIMARY),
         InlineKeyboardButton("🔙 المجلد السابق", callback_data="file_back", style=ButtonStyle.PRIMARY)],
        [InlineKeyboardButton("الرجوع لإدارة البوت", callback_data="file_return_manage", style=ButtonStyle.PRIMARY)]
    ]
    return InlineKeyboardMarkup(buttons)

def admin_users_menu():
    buttons = [
        [InlineKeyboardButton("إدارة تنصيب عضو", callback_data="admin_manage_user_install", style=ButtonStyle.PRIMARY),
         InlineKeyboardButton("حذف تنصيب عضو", callback_data="admin_delete_user_install", style=ButtonStyle.DANGER)],
        [InlineKeyboardButton("إيقاف مؤقت لعضو", callback_data="admin_stop_user", style=ButtonStyle.DANGER),
         InlineKeyboardButton("تشغيل لعضو", callback_data="admin_start_user", style=ButtonStyle.SUCCESS)],
        [InlineKeyboardButton("فك حظر", callback_data="admin_unban", style=ButtonStyle.SUCCESS),
         InlineKeyboardButton("زيادة تنصيب", callback_data="admin_add_limit", style=ButtonStyle.PRIMARY)],
        [InlineKeyboardButton("رجوع", callback_data="admin_back", style=ButtonStyle.PRIMARY)]
    ]
    return InlineKeyboardMarkup(buttons)

@app.on_message(filters.command("start") & filters.private)
async def start_command(client: Client, message: Message):
    db = load_db()
    uid = str(message.from_user.id)
    if uid in db.get("banned", []):
        return await message.reply("أنت محظور من الاستخدام.")
    if uid not in db.get("users", {}):
        user = message.from_user
        name = user.first_name or "No name"
        username = user.username or "No username"
        if "user_details" not in db:
            db["user_details"] = {}
        db["user_details"][uid] = {"name": name, "username": username}
        db["users"][uid] = 2
        save_db(db)
        admin_msg = (
            f"🆕 **مستخدم جديد انضم للبوت!**\n\n"
            f"👤 **الاسم:** {name}\n"
            f"🔹 **اليوزر:** @{username if username != 'No username' else 'لا يوجد'}\n"
            f"🆔 **الايدي:** `{uid}`"
        )
        try:
            await client.send_message(ADMIN_ID, admin_msg)
        except:
            pass
    user_states[message.from_user.id] = {"step": None}
    await message.reply("أهلاً بك. اختر من القائمة أدناه:", reply_markup=main_menu(message.from_user.id))

@app.on_callback_query()
async def callback_handler(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data
    db = load_db()
    if str(user_id) in db.get("banned", []):
        await callback_query.answer("أنت محظور.", show_alert=True)
        return
    if user_id not in user_states or user_states[user_id] is None:
        user_states[user_id] = {"step": None}
    state = user_states[user_id]

    if data == "install_bot":
        await callback_query.answer()
        await check_disk_space(client)
        if db.get("locked", False) and user_id != ADMIN_ID and not is_vip(user_id):
            btn = InlineKeyboardMarkup([[InlineKeyboardButton("المطور", url=f"tg://openmessage?user_id={ADMIN_ID}", style=ButtonStyle.PRIMARY)]])
            await callback_query.message.reply("🔒 عذراً، تم قفل التنصيب حالياً بواسطة المطور. يرجى مراسلته.", reply_markup=btn)
            return

        limit = get_user_limit(user_id)
        slots = get_active_slots(user_id)
        if len(slots) >= limit:
            await callback_query.message.reply("❌ وصلت للحد الأقصى للتنصيبات المسموح بها.")
            return

        available_slot = next((i for i in range(1, limit + 2) if i not in slots), 1)
        state["step"] = "WAITING_FOR_ZIP"
        state["slot"] = available_slot
        await callback_query.message.reply("أرسل ملف البوت (.zip أو .py فقط) الآن:")
        return

    elif data == "delete_install":
        await callback_query.answer()
        slots = get_active_slots(user_id)
        if not slots:
            await callback_query.message.reply("لا يوجد لديك تنصيبات لحذفها.")
            return
        if len(slots) == 1:
            slot = slots[0]
            slot_dir = f"hostings/{user_id}/slot_{slot}"
            if os.path.exists(slot_dir):
                token = None
                bot_dir = f"{slot_dir}/bot"
                if os.path.exists(bot_dir):
                    token = find_bot_token_in_dir(bot_dir)
                process_key = f"{user_id}_{slot}"
                if process_key in running_bots:
                    try:
                        running_bots[process_key].terminate()
                    except:
                        pass
                    del running_bots[process_key]
                shutil.rmtree(slot_dir, ignore_errors=True)
                if token:
                    remove_used_token(token)
                else:
                    remove_user_tokens(user_id, slot)
            await callback_query.message.reply("✅ تم حذف التنصيب بنجاح.")
        else:
            state["step"] = "WAITING_SLOT_DELETE"
            await callback_query.message.reply("لديك أكثر من تنصيب، أدخل الرقم الذي تريد حذفه:")
        return

    elif data == "manage_my_bot":
        await callback_query.answer()
        state["target_id"] = user_id
        slots = get_active_slots(user_id)
        if not slots:
            await callback_query.message.reply("لا يوجد تنصيبات حالياً لإدارتها.")
            return
        if len(slots) == 1:
            state["selected_slot"] = slots[0]
            await callback_query.message.reply(f"تم اختيار التنصيب التلقائي ({slots[0]}). اختر الإجراء:", reply_markup=manage_menu())
        else:
            state["step"] = "WAITING_SLOT_MANAGE"
            await callback_query.message.reply("أدخل رقم التنصيب الذي تريد إدارته:")
        return

    elif data == "manage_users_bots" and user_id == ADMIN_ID:
        await callback_query.answer()
        await callback_query.message.reply("إدارة الأعضاء:", reply_markup=admin_users_menu())
        return

    elif data == "lock_install" and user_id == ADMIN_ID:
        await callback_query.answer()
        db["locked"] = True
        save_db(db)
        await callback_query.message.reply("🔒 تم قفل التنصيب.")
        return

    elif data == "unlock_install" and user_id == ADMIN_ID:
        await callback_query.answer()
        db["locked"] = False
        save_db(db)
        await callback_query.message.reply("🔓 تم فتح التنصيب.")
        return

    elif data == "backup_get" and user_id == ADMIN_ID:
        await callback_query.answer()
        msg = await callback_query.message.reply("⏳ جاري تحضير النسخة الاحتياطية...")
        backup_name = "Backup.zip"
        try:
            with zipfile.ZipFile(backup_name, 'w', zipfile.ZIP_DEFLATED) as zipf:
                if os.path.exists("database.json"):
                    zipf.write("database.json")
                if os.path.exists("hostings"):
                    for root, _, files in os.walk("hostings"):
                        for file in files:
                            zipf.write(os.path.join(root, file))
            await callback_query.message.reply_document(backup_name, caption="📦 النسخة الاحتياطية الخاصة بك جاهزة.")
            os.remove(backup_name)
            await msg.delete()
        except Exception as e:
            await msg.edit_text(f"❌ حدث خطأ أثناء تجهيز النسخة: {e}")
        return

    elif data == "backup_upload" and user_id == ADMIN_ID:
        await callback_query.answer()
        state["step"] = "ADMIN_WAITING_BACKUP"
        await callback_query.message.reply("أرسل ملف النسخة الاحتياطية (`.zip`) الآن:\n⚠️ **تحذير:** رفع النسخة سيقوم بإيقاف البوتات الشغالة واستبدال الملفات ثم إعادة تشغيلهم تلقائياً.")
        return

    elif data == "stats" and user_id == ADMIN_ID:
        await callback_query.answer()
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
        await callback_query.message.reply(report)
        return

    elif data == "list_installs" and user_id == ADMIN_ID:
        await callback_query.answer()
        if not os.path.exists("hostings") or not os.listdir("hostings"):
            await callback_query.message.reply("لا يوجد أي تنصيبات حالياً.")
            return
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
            await callback_query.message.reply("لا يوجد أي تنصيبات حالياً.")
        else:
            await callback_query.message.reply(msg)
        return

    elif data == "vip_add" and user_id == ADMIN_ID:
        await callback_query.answer()
        state["step"] = "ADMIN_VIP_ADD_ID"
        await callback_query.message.reply("أدخل آيدي العضو لرفعه VIP:")
        return

    elif data == "vip_remove" and user_id == ADMIN_ID:
        await callback_query.answer()
        state["step"] = "ADMIN_VIP_REMOVE_ID"
        await callback_query.message.reply("أدخل آيدي العضو لتنزيله من VIP:")
        return

    elif data == "vip_list" and user_id == ADMIN_ID:
        await callback_query.answer()
        vip_data = db.get("vip", {})
        if not vip_data:
            await callback_query.message.reply("لا يوجد أعضاء VIP حالياً.")
            return
        msg = "🌟 **قائمة الأعضاء VIP:**\n\n"
        for uid, expiry in vip_data.items():
            if expiry > time.time():
                remaining = int((expiry - time.time()) / 86400)
                msg += f"👤 **العضو:** `{uid}`\n⏳ **متبقي:** `{remaining}` يوم\n──────────────\n"
        if msg == "🌟 **قائمة الأعضاء VIP:**\n\n":
            await callback_query.message.reply("لا يوجد أعضاء VIP صالحين حالياً.")
        else:
            await callback_query.message.reply(msg)
        return

    elif data == "users_list" and user_id == ADMIN_ID:
        await callback_query.answer()
        users = db.get("users", {})
        user_details = db.get("user_details", {})
        if not users:
            await callback_query.message.reply("لا يوجد مستخدمين مسجلين.")
            return
        msg = "📋 **قائمة المستخدمين:**\n\n"
        for uid in users:
            details = user_details.get(uid, {})
            name = details.get("name", "غير معروف")
            username = details.get("username", "")
            if username:
                user_link = f"[{name}](tg://openmessage?user_id={uid})"
                display = f"{user_link} (@{username})"
            else:
                user_link = f"[{name}](tg://openmessage?user_id={uid})"
                display = f"{user_link} (لا يوجد يوزر)"
            msg += f"🆔 `{uid}` - {display}\n"
        if len(msg) > 4000:
            for x in range(0, len(msg), 4000):
                await callback_query.message.reply(msg[x:x+4000])
        else:
            await callback_query.message.reply(msg)
        return

    elif data == "ban_user" and user_id == ADMIN_ID:
        await callback_query.answer()
        state["step"] = "ADMIN_WAITING_BAN_ID"
        await callback_query.message.reply("أدخل الآيدي (ID) الخاص بالعضو لحظره:")
        return

    elif data == "unban_user" and user_id == ADMIN_ID:
        await callback_query.answer()
        state["step"] = "ADMIN_UNBAN_ID"
        await callback_query.message.reply("أدخل الآيدي (ID) الخاص بالعضو لإلغاء حظره:")
        return

    elif data == "broadcast" and user_id == ADMIN_ID:
        await callback_query.answer()
        state["step"] = "ADMIN_WAITING_BROADCAST_MSG"
        await callback_query.message.reply("أدخل الرسالة التي تريد إرسالها لجميع المستخدمين:")
        return

    elif data in ["disable_security", "enable_security"] and user_id == ADMIN_ID:
        await callback_query.answer()
        if data == "disable_security":
            db["security_enabled"] = False
            save_db(db)
            await callback_query.message.reply("🔒 **تم تعطيل نظام الحماية.** الآن يمكن رفع أي ملف (حتى المشبوه) بدون فحص.", reply_markup=main_menu(user_id))
        else:
            db["security_enabled"] = True
            save_db(db)
            await callback_query.message.reply("🔓 **تم تفعيل نظام الحماية.** سيتم فحص الملفات المرفوعة ومنع الملفات الضارة.", reply_markup=main_menu(user_id))
        return

    elif data.startswith("admin_"):
        if user_id != ADMIN_ID:
            await callback_query.answer("ليس لديك صلاحية.", show_alert=True)
            return
        await callback_query.answer()
        if data == "admin_manage_user_install":
            state["step"] = "ADMIN_WAITING_USER_ID"
            state["action"] = "إدارة تنصيب عضو"
            await callback_query.message.reply("أدخل الآيدي (ID) الخاص بالعضو:")
        elif data == "admin_delete_user_install":
            state["step"] = "ADMIN_WAITING_USER_ID"
            state["action"] = "حذف تنصيب عضو"
            await callback_query.message.reply("أدخل الآيدي (ID) الخاص بالعضو:")
        elif data == "admin_stop_user":
            state["step"] = "ADMIN_WAITING_USER_ID"
            state["action"] = "إيقاف مؤقت لعضو"
            await callback_query.message.reply("أدخل الآيدي (ID) الخاص بالعضو:")
        elif data == "admin_start_user":
            state["step"] = "ADMIN_WAITING_USER_ID"
            state["action"] = "تشغيل لعضو"
            await callback_query.message.reply("أدخل الآيدي (ID) الخاص بالعضو:")
        elif data == "admin_unban":
            state["step"] = "ADMIN_UNBAN_ID"
            await callback_query.message.reply("أدخل الآيدي لفك الحظر:")
        elif data == "admin_add_limit":
            state["step"] = "ADMIN_ADD_LIMIT"
            await callback_query.message.reply("أدخل الآيدي لزيادة الحد:")
        elif data == "admin_back":
            await callback_query.message.delete()
            await callback_query.message.reply("القائمة الرئيسية:", reply_markup=main_menu(user_id))
        return

    elif data.startswith("manage_"):
        target_id = state.get("target_id", user_id)
        slot = state.get("selected_slot")
        if not slot:
            await callback_query.answer("يرجى اختيار التنصيب أولاً.", show_alert=True)
            return

        if data == "manage_back":
            await callback_query.message.delete()
            await callback_query.message.reply("القائمة الرئيسية:", reply_markup=main_menu(user_id))
            user_states[user_id] = {"step": None}
            await callback_query.answer()
            return

        process_key = f"{target_id}_{slot}"
        user_dir = f"hostings/{target_id}/slot_{slot}"
        bot_dir = f"{user_dir}/bot"

        if data == "manage_log":
            log_path = f"{user_dir}/log.txt"
            if os.path.exists(log_path):
                with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                    log_text = "".join(f.readlines()[-50:])
                await callback_query.message.reply(f"**سجل التنصيب:**\n```\n{log_text[-4000:]}\n```")
            else:
                await callback_query.message.reply("لا يوجد سجل حتى الآن.")
            await callback_query.answer()
            return

        elif data == "manage_status":
            if process_key in running_bots and running_bots[process_key].poll() is None:
                status = "يعمل 🟢"
            else:
                status = "متوقف ⚪"
            await callback_query.message.reply(f"الحالة: {status}")
            await callback_query.answer()
            return

        elif data == "manage_stop":
            if process_key in running_bots:
                try:
                    running_bots[process_key].terminate()
                except:
                    pass
                del running_bots[process_key]
                await callback_query.message.reply("تم الإيقاف المؤقت بنجاح.")
            else:
                await callback_query.message.reply("البوت متوقف بالفعل.")
            await callback_query.answer()
            return

        elif data == "manage_start":
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
                await callback_query.message.reply("تم تشغيل البوت بنجاح.")
            else:
                await callback_query.message.reply("لم يتم العثور على ملف py للتشغيل.")
            await callback_query.answer()
            return

        elif data == "manage_restart":
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
                await callback_query.message.reply("✅ تم إعادة تشغيل البوت بنجاح.")
            else:
                await callback_query.message.reply("❌ لم يتم العثور على ملف التشغيل.")
            await callback_query.answer()
            return

        elif data == "manage_input":
            if process_key in running_bots and running_bots[process_key].poll() is None:
                state["step"] = "WAITING_INPUT"
                await callback_query.message.reply("أدخل القيمة الآن:")
            else:
                await callback_query.message.reply("البوت متوقف، لا يمكن إرسال بيانات له.")
            await callback_query.answer()
            return

        elif data == "manage_files":
            state["current_dir"] = bot_dir
            await callback_query.message.reply("أهلاً بك في قسم إدارة الملفات:", reply_markup=file_manage_menu())
            await callback_query.answer()
            return

        elif data == "manage_install_lib":
            state["step"] = "WAITING_LIBRARY"
            await callback_query.message.reply("أدخل اسم المكتبة التي تريد تثبيتها (مثل: requests):")
            await callback_query.answer()
            return

        await callback_query.answer("أمر غير معروف.")
        return

    elif data.startswith("file_"):
        current_dir = state.get("current_dir")
        if not current_dir or not os.path.exists(current_dir):
            await callback_query.answer("الرجاء الدخول لإدارة الملفات أولاً.", show_alert=True)
            return

        target_id = state.get("target_id", user_id)
        slot = state.get("selected_slot")
        base_bot_dir = os.path.abspath(f"hostings/{target_id}/slot_{slot}/bot")

        if data == "file_list":
            items = os.listdir(current_dir)
            if not items:
                await callback_query.message.reply("المجلد فارغ.")
            else:
                msg = "**الملفات والمجلدات:**\n\n"
                for item in sorted(items):
                    full = os.path.join(current_dir, item)
                    if os.path.isdir(full):
                        msg += f"📁 `{item}`\n"
                    else:
                        msg += f"📄 `{item}`\n"
                await callback_query.message.reply(msg)
            await callback_query.answer()
            return

        elif data == "file_enter":
            state["step"] = "WAITING_FOLDER_NAME"
            await callback_query.message.reply("أدخل اسم المجلد الذي تريد الدخول إليه بالضبط:")
            await callback_query.answer()
            return

        elif data == "file_back":
            abs_current = os.path.abspath(current_dir)
            if abs_current == base_bot_dir:
                await callback_query.message.reply("أنت في المجلد الرئيسي (الأساسي) للبوت، لا يمكن الرجوع أكثر.")
            else:
                state["current_dir"] = os.path.dirname(abs_current)
                await callback_query.message.reply("تم الرجوع للمجلد السابق. اضغط 'عرض الملفات'.")
            await callback_query.answer()
            return

        elif data == "file_delete":
            state["step"] = "WAITING_DELETE_FILE_NAME"
            await callback_query.message.reply("أدخل اسم الملف أو المجلد الذي تريد حذفه (بما في ذلك الصيغة):")
            await callback_query.answer()
            return

        elif data == "file_add":
            state["step"] = "WAITING_ADD_FILE"
            await callback_query.message.reply("أرسل الملف الجديد الآن.\nسيتم حفظه بنفس اسمه في المجلد الحالي.")
            await callback_query.answer()
            return

        elif data == "file_replace":
            state["step"] = "WAITING_REPLACE_FILE"
            await callback_query.message.reply("أرسل الملف الجديد الآن.\n⚠️ **ملاحظة:** يجب أن يكون اسم الملف المرسل هو نفس اسم الملف الموجود في المجلد ليتم استبداله.")
            await callback_query.answer()
            return

        elif data == "file_restart":
            process_key = f"{target_id}_{slot}"
            bot_dir = f"hostings/{target_id}/slot_{slot}/bot"
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
                    stdout=open(f"hostings/{target_id}/slot_{slot}/log.txt", "a"),
                    stderr=subprocess.STDOUT
                )
                running_bots[process_key] = p
                await callback_query.message.reply("✅ تم إعادة تشغيل البوت بنجاح.")
            else:
                await callback_query.message.reply("❌ لم يتم العثور على ملف التشغيل.")
            await callback_query.answer()
            return

        elif data == "file_return_manage":
            await callback_query.message.delete()
            await callback_query.message.reply("قائمة الإدارة:", reply_markup=manage_menu())
            await callback_query.answer()
            return

        await callback_query.answer("أمر غير معروف.")
        return

    await callback_query.answer("أمر غير معروف.")

@app.on_message(filters.text & filters.private)
async def handle_texts(client: Client, message: Message):
    user_id = message.from_user.id
    text = message.text
    db = load_db()
    if str(user_id) in db.get("banned", []):
        return await message.reply("أنت محظور من استخدام البوت.")
    if user_id not in user_states or user_states[user_id] is None:
        user_states[user_id] = {"step": None}
    state = user_states[user_id]
    step = state.get("step")

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

    if step == "WAITING_LIBRARY":
        lib_name = text.strip()
        if not lib_name:
            await message.reply("الرجاء إدخال اسم مكتبة صحيح.")
            return
        try:
            result = subprocess.run(["pip", "install", lib_name], capture_output=True, text=True)
            if result.returncode == 0:
                await message.reply(f"✅ تم تثبيت المكتبة `{lib_name}` بنجاح.")
            else:
                await message.reply(f"❌ فشل تثبيت المكتبة `{lib_name}`.\nالخطأ:\n```\n{result.stderr[:500]}\n```")
        except Exception as e:
            await message.reply(f"❌ حدث خطأ أثناء التثبيت: {e}")
        state["step"] = None
        return

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

    if step == "WAITING_SLOT_DELETE" and text.isdigit():
        slot = int(text)
        slot_dir = f"hostings/{user_id}/slot_{slot}"
        if os.path.exists(slot_dir):
            token = None
            bot_dir = f"{slot_dir}/bot"
            if os.path.exists(bot_dir):
                token = find_bot_token_in_dir(bot_dir)
            process_key = f"{user_id}_{slot}"
            if process_key in running_bots:
                try:
                    running_bots[process_key].terminate()
                except:
                    pass
                del running_bots[process_key]
            shutil.rmtree(slot_dir, ignore_errors=True)
            if token:
                remove_used_token(token)
            else:
                remove_user_tokens(user_id, slot)
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
            try:
                await client.send_message(int(uid), "✅ **تم إلغاء حظرك، يمكنك استخدام البوت الآن.**")
            except:
                pass
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
        try:
            await client.send_message(int(uid), f"🌟 **تم ترقيتك إلى VIP لمدة {days} يوم!**\nشكراً لك.")
        except:
            pass
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

    if step == "ADMIN_WAITING_BAN_ID" and text.isdigit():
        uid = str(text)
        if uid in db.get("banned", []):
            await message.reply("❌ هذا المستخدم محظور بالفعل.")
        else:
            db["banned"].append(uid)
            save_db(db)
            try:
                await client.send_message(int(uid), "⚠️ **تم حظرك من استخدام البوت.**")
            except:
                pass
            await message.reply(f"✅ تم حظر المستخدم `{uid}` بنجاح.")
        state["step"] = None
        return

    if step == "ADMIN_WAITING_BROADCAST_MSG":
        broadcast_msg = text
        users = db.get("users", {})
        if not users:
            return await message.reply("لا يوجد مستخدمين لإرسال الإذاعة لهم.")
        await message.reply(f"⏳ جاري إرسال الإذاعة إلى {len(users)} مستخدم...")
        success = 0
        fail = 0
        for uid in users:
            try:
                await client.send_message(int(uid), broadcast_msg)
                success += 1
            except:
                fail += 1
            await asyncio.sleep(0.05)
        report = f"✅ **تقرير الإذاعة:**\nتم الإرسال بنجاح: {success}\nفشل الإرسال: {fail}"
        await message.reply(report)
        state["step"] = None
        return

    await message.reply("هذا الأمر غير معروف، استخدم القائمة.", reply_markup=main_menu(user_id))

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
        bot_dir = f"{user_dir}/bot"
        if os.path.exists(bot_dir):
            token = find_bot_token_in_dir(bot_dir)
            if token:
                remove_used_token(token)
            else:
                remove_user_tokens(target_id, slot)
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

@app.on_message(filters.document & filters.private)
async def handle_docs(client: Client, message: Message):
    user_id = message.from_user.id
    state = user_states.get(user_id, {})
    step = state.get("step")
    file_name = message.document.file_name

    if step == "ADMIN_WAITING_BACKUP" and user_id == ADMIN_ID:
        if not file_name.endswith(".zip"):
            return await message.reply("❌ يرجى إرسال ملف بصيغة .zip فقط.")

        msg = await message.reply("⏳ جاري رفع واستخراج النسخة الاحتياطية...")

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

        db = load_db()
        security_enabled = db.get("security_enabled", True)
        if security_enabled and scan_for_malicious(bot_dir):
            shutil.rmtree(f"hostings/{user_id}/slot_{slot}", ignore_errors=True)
            state["step"] = None
            return await msg.edit_text("❌ تم رفض الملف لاحتوائه على أكواد ضارة أو محاولة اختراق.")

        token = find_bot_token_in_dir(bot_dir)
        if token and is_token_used(token, user_id, slot):
            shutil.rmtree(f"hostings/{user_id}/slot_{slot}", ignore_errors=True)
            state["step"] = None
            return await msg.edit_text("❌ هذا البوت يعمل بالفعل على تنصيب آخر، لا يمكن تشغيل نسختين.")

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

        if token:
            add_used_token(token, user_id, slot)

        await msg.edit_text(f"✅ تم تنصيب البوت بنجاح. (رقم التنصيب: {slot})", reply_markup=main_menu(user_id))

        admin_report = (
            "🔔 **إشعار تنصيب جديد!**\n\n"
            f"👤 **المستخدم:** [{message.from_user.first_name}](tg://openmessage?user_id={user_id})\n"
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

app.run()
