import os
import json
import re
import discord
from discord.ext import commands
from datetime import datetime, timezone, timedelta
from flask import Flask
from threading import Thread

# -------------------------
# Flask Keep-Alive (Render Web Service)
# -------------------------
app = Flask(__name__)

@app.route('/')
def home():
    return "✅ Bot is running on Render!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, threaded=True)

# -------------------------
# Discord Bot Setup
# -------------------------
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

OWNER_ID = 1363029073328078848  # replace with your Discord ID
LOG_CHANNEL_NAME = "security-logs"

# Role allowed to send links
SAFE_ROLE_ID = 1317405000863060050  # replace with your moderator/admin role ID

# User IDs allowed to send links even without the role
SAFE_LINK_IDS = {
    1409483924383465603,
    1417563976249774120,
    1417570656718950564
}

# -------------------------
# Whitelist System
# -------------------------
WHITELIST_FILE = "whitelist.json"

def load_whitelist():
    with open(WHITELIST_FILE, "r") as f:
        data = json.load(f)
        return set(data)  # expects a list of IDs

def save_whitelist(whitelist):
    with open(WHITELIST_FILE, "w") as f:
        json.dump(list(whitelist), f, indent=4)

whitelist = load_whitelist()
recently_punished = {}
log_channels = {}

# -------------------------
# Helper Functions
# -------------------------
async def get_log_channel(guild):
    if guild.id in log_channels:
        channel = guild.get_channel(log_channels[guild.id])
        if channel:
            return channel
    
    channel = discord.utils.get(guild.text_channels, name=LOG_CHANNEL_NAME)
    if not channel:
        try:
            channel = await guild.create_text_channel(LOG_CHANNEL_NAME)
        except Exception:
            return None
    return channel

async def send_log(guild, message):
    channel = await get_log_channel(guild)
    if channel:
        await channel.send(message)

async def punish_and_revert(guild, executor, reason: str):
    now = datetime.now(timezone.utc).timestamp()
    if executor.id in recently_punished and now - recently_punished[executor.id] < 15:
        return
    recently_punished[executor.id] = now

    try:
        await guild.ban(executor, reason=reason, delete_message_seconds=0)
    except Exception:
        pass
    await send_log(guild, f"🚨 **Auto-ban** → {executor.mention} (`{executor.id}`) — {reason}")

def is_whitelisted(user, guild=None):
    if user.id in whitelist:
        return True
    if guild:
        member = guild.get_member(user.id)
        if member and member.guild_permissions.administrator:
            return True
    return False

# -------------------------
# Bot Events
# -------------------------
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")

@bot.event
async def on_member_ban(guild, user):
    async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.ban):
        executor = entry.user
        if executor.id != OWNER_ID and not is_whitelisted(executor, guild):
            await punish_and_revert(guild, executor, f"Unauthorized ban attempt on {user}")

@bot.event
async def on_member_remove(member):
    guild = member.guild
    async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.kick):
        executor = entry.user
        if executor.id != OWNER_ID and not is_whitelisted(executor, guild):
            await punish_and_revert(guild, executor, f"Unauthorized kick attempt on {member}")

@bot.event
async def on_guild_channel_create(channel):
    guild = channel.guild
    async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_create):
        executor = entry.user
        if executor.id != OWNER_ID and not is_whitelisted(executor, guild):
            await punish_and_revert(guild, executor, "Unauthorized channel creation")
            await channel.delete()

@bot.event
async def on_guild_channel_delete(channel):
    guild = channel.guild
    async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_delete):
        executor = entry.user
        if executor.id != OWNER_ID and not is_whitelisted(executor, guild):
            await punish_and_revert(guild, executor, "Unauthorized channel deletion")

@bot.event
async def on_guild_role_delete(role):
    guild = role.guild
    async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.role_delete):
        executor = entry.user
        if executor.id != OWNER_ID and not is_whitelisted(executor, guild):
            await punish_and_revert(guild, executor, f"Unauthorized role deletion ({role.name})")

@bot.event
async def on_guild_role_update(before, after):
    guild = before.guild
    async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.role_update):
        executor = entry.user
        if executor.id != OWNER_ID and not is_whitelisted(executor, guild):
            await punish_and_revert(guild, executor, f"Unauthorized role update ({before.name})")

# -------------------------
# Anti-Link Protection
# -------------------------
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    url_pattern = r"(https?://\S+)"
    if re.search(url_pattern, message.content):
        # Check if user is exempt
        if (SAFE_ROLE_ID not in [role.id for role in message.author.roles] 
            and message.author.id not in SAFE_LINK_IDS):
            try:
                await message.delete()
            except Exception:
                pass
            try:
                duration = timedelta(minutes=10)
                await message.author.timeout(duration, reason="Sent a link without permission")
                await send_log(message.guild, f"⏳ {message.author.mention} was timed out for 10m (sent link).")
            except Exception as e:
                print(f"Failed to timeout: {e}")

    await bot.process_commands(message)

# -------------------------
# Commands
# -------------------------
@bot.command()
async def setlog(ctx, channel: discord.TextChannel):
    if ctx.author.id != OWNER_ID:
        return await ctx.send("❌ You are not allowed to use this command.")
    log_channels[ctx.guild.id] = channel.id
    await ctx.send(f"✅ Log channel set to {channel.mention}")

@bot.command()
async def showlog(ctx):
    channel = await get_log_channel(ctx.guild)
    if channel:
        await ctx.send(f"📑 Current log channel is {channel.mention}")
    else:
        await ctx.send("⚠️ No log channel found.")

@bot.command()
async def whitelist_show(ctx):
    ids = ", ".join([str(uid) for uid in whitelist])
    await ctx.send(f"👥 Whitelisted IDs: {ids}")

@bot.command()
async def ping(ctx):
    await ctx.send("🏓 Pong!")

# -------------------------
# Run Flask + Bot
# -------------------------
if __name__ == "__main__":
    Thread(target=run_flask).start()

    TOKEN = os.environ.get("TOKEN")
    if not TOKEN:
        raise ValueError("⚠️ TOKEN not found in environment variables!")
    
    bot.run(TOKEN)
