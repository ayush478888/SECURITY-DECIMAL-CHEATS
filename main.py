import discord
from discord.ext import commands
import asyncio
from datetime import datetime
import os

# -------------------------
# CONFIG
# -------------------------
OWNER_ID = 1363029073328078848  # replace with your Discord ID
LOG_CHANNEL_NAME = "security-logs"

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

whitelist = set([OWNER_ID])   # trusted users
recently_punished = {}        # cooldown memory
log_channels = {}             # stores guild_id -> channel_id


# -------------------------
# Helper Functions
# -------------------------
def is_whitelisted(user: discord.Member):
    return user.id in whitelist or user.guild_permissions.administrator


async def get_log_channel(guild: discord.Guild):
    # If custom log channel set, use it
    if guild.id in log_channels:
        channel = guild.get_channel(log_channels[guild.id])
        if channel:
            return channel
    
    # fallback to default "security-logs"
    channel = discord.utils.get(guild.text_channels, name=LOG_CHANNEL_NAME)
    if not channel:
        try:
            channel = await guild.create_text_channel(LOG_CHANNEL_NAME)
        except Exception:
            return None
    return channel


async def send_log(guild: discord.Guild, message: str):
    channel = await get_log_channel(guild)
    if channel:
        await channel.send(message)


async def punish_and_revert(guild: discord.Guild, executor: discord.Member, reason: str):
    now = datetime.utcnow().timestamp()
    # Cooldown: 15s per user
    if executor.id in recently_punished and now - recently_punished[executor.id] < 15:
        return
    recently_punished[executor.id] = now

    try:
        await guild.ban(executor, reason=reason, delete_message_days=0)
        await send_log(guild, f"🚨 **Auto-ban** → {executor.mention} (`{executor.id}`) — {reason}")
    except Exception as e:
        await send_log(guild, f"⚠️ Failed to punish {executor.mention} — {reason}\nError: `{e}`")


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
        if executor.id != OWNER_ID and not is_whitelisted(executor):
            await punish_and_revert(guild, executor, f"Unauthorized ban attempt on {user}")


@bot.event
async def on_member_remove(member):
    guild = member.guild
    async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.kick):
        executor = entry.user
        if executor.id != OWNER_ID and not is_whitelisted(executor):
            await punish_and_revert(guild, executor, f"Unauthorized kick attempt on {member}")


@bot.event
async def on_guild_channel_create(channel):
    guild = channel.guild
    async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_create):
        executor = entry.user
        if executor.id != OWNER_ID and not is_whitelisted(executor):
            await punish_and_revert(guild, executor, "Unauthorized channel creation")
            try:
                await channel.delete()
            except Exception:
                pass


@bot.event
async def on_guild_channel_delete(channel):
    guild = channel.guild
    async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_delete):
        executor = entry.user
        if executor.id != OWNER_ID and not is_whitelisted(executor):
            await punish_and_revert(guild, executor, "Unauthorized channel deletion")


@bot.event
async def on_guild_role_delete(role):
    guild = role.guild
    async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.role_delete):
        executor = entry.user
        if executor.id != OWNER_ID and not is_whitelisted(executor):
            await punish_and_revert(guild, executor, f"Unauthorized role deletion ({role.name})")


@bot.event
async def on_guild_role_update(before, after):
    guild = before.guild
    async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.role_update):
        executor = entry.user
        if executor.id != OWNER_ID and not is_whitelisted(executor):
            await punish_and_revert(guild, executor, f"Unauthorized role update ({before.name})")


# -------------------------
# Commands
# -------------------------
@bot.command()
async def setlog(ctx, channel: discord.TextChannel):
    """Set a custom log channel for this server"""
    if ctx.author.id != OWNER_ID:
        return await ctx.send("❌ You are not allowed to use this command.")

    log_channels[ctx.guild.id] = channel.id
    await ctx.send(f"✅ Log channel set to {channel.mention}")


@bot.command()
async def showlog(ctx):
    """Show current log channel"""
    channel = await get_log_channel(ctx.guild)
    if channel:
        await ctx.send(f"📑 Current log channel is {channel.mention}")
    else:
        await ctx.send("⚠️ No log channel found.")


@bot.command()
async def whitelist_add(ctx, member: discord.Member):
    if ctx.author.id != OWNER_ID:
        return await ctx.send("❌ You are not allowed to use this command.")
    whitelist.add(member.id)
    await ctx.send(f"✅ {member.mention} has been whitelisted.")


@bot.command()
async def whitelist_remove(ctx, member: discord.Member):
    if ctx.author.id != OWNER_ID:
        return await ctx.send("❌ You are not allowed to use this command.")
    whitelist.discard(member.id)
    await ctx.send(f"✅ {member.mention} has been removed from whitelist.")


@bot.command()
async def whitelist_show(ctx):
    ids = ", ".join([str(uid) for uid in whitelist])
    await ctx.send(f"👥 Whitelisted IDs: {ids}")


# -------------------------
# Run the Bot
# -------------------------
bot.run(os.getenv("DISCORD_TOKEN"))
