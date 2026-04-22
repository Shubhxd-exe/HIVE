import discord
from discord.ext import commands, tasks
import asyncio
import datetime
import pytz
import os
import time
import re
from dotenv import load_dotenv

load_dotenv()

# ─── CONFIG ───────────────────────────────────────────────────────────────────
PREFIX    = ","
BOT_TOKEN = os.getenv("BOT_TOKEN")
TIMEZONE  = os.getenv("TIMEZONE", "Asia/Kolkata")

# ─── INTENTS ──────────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

# ─── IN-MEMORY STORAGE ────────────────────────────────────────────────────────
autoresponders   = {}   # guild_id → {trigger: response}
clock_channels   = {}   # guild_id → channel_id   (live clock)
reminders        = []   # list of reminder dicts

# ─── COLORS & HELPER ──────────────────────────────────────────────────────────
COLOR_SUCCESS  = 0x57F287   # green
COLOR_ERROR    = 0xED4245   # red
COLOR_INFO     = 0x5865F2   # blurple
COLOR_WARN     = 0xFEE75C   # yellow
COLOR_PURPLE   = 0x9B59B6
COLOR_CYAN     = 0x1ABC9C
COLOR_GOLD     = 0xF1C40F

def success_embed(title, desc=None, footer=None):
    e = discord.Embed(title=f"✅  {title}", description=desc, color=COLOR_SUCCESS)
    e.set_footer(text=footer or "ModBot • made with ❤️")
    e.timestamp = datetime.datetime.utcnow()
    return e

def error_embed(title, desc=None):
    e = discord.Embed(title=f"❌  {title}", description=desc, color=COLOR_ERROR)
    e.set_footer(text="ModBot")
    e.timestamp = datetime.datetime.utcnow()
    return e

def info_embed(title, desc=None, color=COLOR_INFO, footer=None):
    e = discord.Embed(title=title, description=desc, color=color)
    e.set_footer(text=footer or "ModBot • use ,help for commands")
    e.timestamp = datetime.datetime.utcnow()
    return e

# ══════════════════════════════════════════════════════════════════════════════
# EVENTS
# ══════════════════════════════════════════════════════════════════════════════

@bot.event
async def on_ready():
    print(f"✅  Logged in as {bot.user} (ID: {bot.user.id})")
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name=f"{PREFIX}help • ModBot"
        )
    )
    update_clock.start()
    check_reminders.start()


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send(embed=error_embed("No Permission", "You don't have permission to use this command."))
    elif isinstance(error, commands.BotMissingPermissions):
        await ctx.send(embed=error_embed("Bot Missing Permissions", str(error)))
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send(embed=error_embed("Member Not Found", "Could not find that member."))
    elif isinstance(error, commands.CommandNotFound):
        pass  # silently ignore unknown commands
    else:
        await ctx.send(embed=error_embed("Error", str(error)))


@bot.event
async def on_message(message):
    if message.author.bot:
        return
    # ── Auto-responders ──
    guild_ars = autoresponders.get(message.guild.id if message.guild else None, {})
    content_lower = message.content.lower()
    for trigger, response in guild_ars.items():
        if trigger.lower() in content_lower:
            e = discord.Embed(
                description=f"💬  {response}",
                color=COLOR_CYAN
            )
            e.set_footer(text=f"Auto-responder • trigger: {trigger}")
            await message.channel.send(embed=e)
            break
    await bot.process_commands(message)

# ══════════════════════════════════════════════════════════════════════════════
# HELP COMMAND  (mirrors the Qirox-style UI)
# ══════════════════════════════════════════════════════════════════════════════

@bot.command(name="help")
async def help_cmd(ctx, category: str = None):
    categories = {
        "moderation": {
            "icon": "🔨",
            "desc": "Ban, kick, mute, warn members",
            "commands": [
                (f"`{PREFIX}ban @user [reason]`",    "Ban a member"),
                (f"`{PREFIX}kick @user [reason]`",   "Kick a member"),
                (f"`{PREFIX}timeout @user <time>`",  "Timeout a member (e.g. 10m, 1h)"),
                (f"`{PREFIX}untimeout @user`",        "Remove timeout"),
                (f"`{PREFIX}warn @user [reason]`",   "Warn a member"),
                (f"`{PREFIX}warnings @user`",        "View warnings"),
                (f"`{PREFIX}clearwarn @user`",       "Clear all warnings"),
                (f"`{PREFIX}purge <amount>`",        "Bulk delete messages"),
                (f"`{PREFIX}slowmode <seconds>`",    "Set slowmode in channel"),
                (f"`{PREFIX}lock`",                  "Lock current channel"),
                (f"`{PREFIX}unlock`",                "Unlock current channel"),
                (f"`{PREFIX}mute @user`",            "Mute a member (role-based)"),
                (f"`{PREFIX}unmute @user`",          "Unmute a member"),
                (f"`{PREFIX}nick @user <name>`",     "Change member nickname"),
            ]
        },
        "utility": {
            "icon": "🛠️",
            "desc": "Handy utility commands",
            "commands": [
                (f"`{PREFIX}time`",                  "Show current time"),
                (f"`{PREFIX}clock #channel`",        "Live clock in a channel"),
                (f"`{PREFIX}stopclock`",             "Stop the live clock"),
                (f"`{PREFIX}remind <time> <msg>`",   "Set a reminder"),
                (f"`{PREFIX}reminders`",             "List your reminders"),
                (f"`{PREFIX}dm @user <message>`",    "DM a user via the bot"),
                (f"`{PREFIX}serverinfo`",            "Server information"),
                (f"`{PREFIX}userinfo [@user]`",      "User information"),
                (f"`{PREFIX}avatar [@user]`",        "Get user avatar"),
                (f"`{PREFIX}ping`",                  "Bot latency"),
                (f"`{PREFIX}invite`",                "Bot invite link"),
            ]
        },
        "autoresponder": {
            "icon": "🤖",
            "desc": "Auto-responder management",
            "commands": [
                (f"`{PREFIX}ar <trigger> | <response>`", "Add an auto-responder"),
                (f"`{PREFIX}arlist`",                    "List all auto-responders"),
                (f"`{PREFIX}ardel <trigger>`",           "Delete an auto-responder"),
            ]
        },
    }

    if category and category.lower() in categories:
        cat = categories[category.lower()]
        e = discord.Embed(
            title=f"{cat['icon']}  {category.capitalize()} Commands",
            description=cat["desc"],
            color=COLOR_PURPLE
        )
        for cmd_name, cmd_desc in cat["commands"]:
            e.add_field(name=cmd_name, value=cmd_desc, inline=False)
        e.set_footer(text=f"ModBot • Prefix: {PREFIX}")
        e.timestamp = datetime.datetime.utcnow()
        await ctx.send(embed=e)
        return

    # Main help menu
    e = discord.Embed(
        title="✨  Hey, I'm ModBot™",
        description=(
            f"A **powerful moderation & utility bot** for your server!\n\n"
            f"• **Prefix:** `{PREFIX}`\n"
            f"• Type `{PREFIX}help <category>` for detailed commands\n"
            f"• **Total Commands:** 30+"
        ),
        color=COLOR_PURPLE
    )
    e.add_field(
        name="",
        value="\n".join(
            f"{v['icon']}  **{k.capitalize()}** — {v['desc']}"
            for k, v in categories.items()
        ),
        inline=False
    )
    e.add_field(
        name="📌  Quick Examples",
        value=(
            f"`{PREFIX}ban @User Spamming`\n"
            f"`{PREFIX}ar hello | Hey there!`\n"
            f"`{PREFIX}clock #general`\n"
            f"`{PREFIX}remind 30m Check the oven`"
        ),
        inline=False
    )
    e.set_footer(text=f"ModBot™ • Prefix: {PREFIX} • use {PREFIX}invite for the invite link")
    e.timestamp = datetime.datetime.utcnow()
    if bot.user.avatar:
        e.set_thumbnail(url=bot.user.avatar.url)
    await ctx.send(embed=e)

# ══════════════════════════════════════════════════════════════════════════════
# MODERATION COMMANDS
# ══════════════════════════════════════════════════════════════════════════════

warnings_db: dict[int, dict[int, list]] = {}  # guild_id → {user_id: [reasons]}

@bot.command()
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason: str = "No reason provided"):
    await member.ban(reason=reason)
    e = success_embed(
        "Member Banned",
        f"**{member}** has been banned.\n\n📝 **Reason:** {reason}",
        footer=f"Banned by {ctx.author}"
    )
    e.set_thumbnail(url=member.display_avatar.url)
    await ctx.send(embed=e)


@bot.command()
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason: str = "No reason provided"):
    await member.kick(reason=reason)
    e = success_embed(
        "Member Kicked",
        f"**{member}** has been kicked.\n\n📝 **Reason:** {reason}",
        footer=f"Kicked by {ctx.author}"
    )
    e.set_thumbnail(url=member.display_avatar.url)
    await ctx.send(embed=e)


def parse_duration(s: str) -> int:
    """Return seconds from strings like 10m, 2h, 1d."""
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    match = re.fullmatch(r"(\d+)([smhd])", s.lower())
    if not match:
        raise ValueError(f"Invalid duration: {s}")
    return int(match.group(1)) * units[match.group(2)]


@bot.command()
@commands.has_permissions(moderate_members=True)
async def timeout(ctx, member: discord.Member, duration: str, *, reason: str = "No reason provided"):
    seconds = parse_duration(duration)
    until = discord.utils.utcnow() + datetime.timedelta(seconds=seconds)
    await member.timeout(until, reason=reason)
    e = success_embed(
        "Member Timed Out",
        f"**{member}** has been timed out for **{duration}**.\n\n📝 **Reason:** {reason}",
        footer=f"Timed out by {ctx.author}"
    )
    await ctx.send(embed=e)


@bot.command()
@commands.has_permissions(moderate_members=True)
async def untimeout(ctx, member: discord.Member):
    await member.timeout(None)
    await ctx.send(embed=success_embed("Timeout Removed", f"**{member}**'s timeout has been removed."))


@bot.command()
@commands.has_permissions(manage_messages=True)
async def warn(ctx, member: discord.Member, *, reason: str = "No reason provided"):
    gid, uid = ctx.guild.id, member.id
    warnings_db.setdefault(gid, {}).setdefault(uid, []).append(reason)
    count = len(warnings_db[gid][uid])
    e = discord.Embed(
        title="⚠️  Member Warned",
        description=f"**{member}** has been warned.\n\n📝 **Reason:** {reason}\n📊 **Total Warnings:** {count}",
        color=COLOR_WARN
    )
    e.set_footer(text=f"Warned by {ctx.author}")
    e.timestamp = datetime.datetime.utcnow()
    await ctx.send(embed=e)


@bot.command()
@commands.has_permissions(manage_messages=True)
async def warnings(ctx, member: discord.Member):
    gid, uid = ctx.guild.id, member.id
    warns = warnings_db.get(gid, {}).get(uid, [])
    if not warns:
        await ctx.send(embed=info_embed(f"⚠️  Warnings for {member}", "No warnings found.", color=COLOR_GOLD))
        return
    desc = "\n".join(f"`{i+1}.` {w}" for i, w in enumerate(warns))
    await ctx.send(embed=info_embed(f"⚠️  Warnings for {member}", desc, color=COLOR_WARN))


@bot.command()
@commands.has_permissions(manage_messages=True)
async def clearwarn(ctx, member: discord.Member):
    gid, uid = ctx.guild.id, member.id
    warnings_db.get(gid, {}).pop(uid, None)
    await ctx.send(embed=success_embed("Warnings Cleared", f"All warnings for **{member}** have been cleared."))


@bot.command()
@commands.has_permissions(manage_messages=True)
async def purge(ctx, amount: int):
    if amount < 1 or amount > 500:
        await ctx.send(embed=error_embed("Invalid Amount", "Please provide a number between 1 and 500."))
        return
    deleted = await ctx.channel.purge(limit=amount + 1)
    m = await ctx.send(embed=success_embed("Messages Purged", f"Deleted **{len(deleted)-1}** messages."))
    await asyncio.sleep(3)
    await m.delete()


@bot.command()
@commands.has_permissions(manage_channels=True)
async def slowmode(ctx, seconds: int):
    await ctx.channel.edit(slowmode_delay=seconds)
    await ctx.send(embed=success_embed("Slowmode Set", f"Slowmode set to **{seconds}s** in {ctx.channel.mention}."))


@bot.command()
@commands.has_permissions(manage_channels=True)
async def lock(ctx):
    overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
    overwrite.send_messages = False
    await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
    await ctx.send(embed=success_embed("Channel Locked", f"{ctx.channel.mention} has been locked 🔒"))


@bot.command()
@commands.has_permissions(manage_channels=True)
async def unlock(ctx):
    overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
    overwrite.send_messages = True
    await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
    await ctx.send(embed=success_embed("Channel Unlocked", f"{ctx.channel.mention} has been unlocked 🔓"))


@bot.command()
@commands.has_permissions(manage_roles=True)
async def mute(ctx, member: discord.Member):
    mute_role = discord.utils.get(ctx.guild.roles, name="Muted")
    if not mute_role:
        mute_role = await ctx.guild.create_role(name="Muted")
        for channel in ctx.guild.channels:
            await channel.set_permissions(mute_role, send_messages=False, speak=False)
    await member.add_roles(mute_role)
    await ctx.send(embed=success_embed("Member Muted", f"**{member}** has been muted 🔇"))


@bot.command()
@commands.has_permissions(manage_roles=True)
async def unmute(ctx, member: discord.Member):
    mute_role = discord.utils.get(ctx.guild.roles, name="Muted")
    if mute_role and mute_role in member.roles:
        await member.remove_roles(mute_role)
        await ctx.send(embed=success_embed("Member Unmuted", f"**{member}** has been unmuted 🔊"))
    else:
        await ctx.send(embed=error_embed("Not Muted", f"**{member}** is not muted."))


@bot.command()
@commands.has_permissions(manage_nicknames=True)
async def nick(ctx, member: discord.Member, *, name: str):
    old = member.display_name
    await member.edit(nick=name)
    await ctx.send(embed=success_embed("Nickname Changed", f"**{old}** → **{name}**"))

# ══════════════════════════════════════════════════════════════════════════════
# UTILITY COMMANDS
# ══════════════════════════════════════════════════════════════════════════════

@bot.command(name="time")
async def time_cmd(ctx):
    tz = pytz.timezone(TIMEZONE)
    now = datetime.datetime.now(tz)
    e = discord.Embed(
        title="🕐  Current Time",
        description=f"```\n{now.strftime('%A, %B %d %Y')}\n{now.strftime('%I:%M:%S %p')} ({TIMEZONE})\n```",
        color=COLOR_CYAN
    )
    e.set_footer(text="ModBot • ,clock #channel to add a live clock")
    e.timestamp = datetime.datetime.utcnow()
    await ctx.send(embed=e)


@bot.command(name="clock")
@commands.has_permissions(manage_channels=True)
async def clock_cmd(ctx, channel: discord.TextChannel = None):
    channel = channel or ctx.channel
    clock_channels[ctx.guild.id] = channel.id
    tz = pytz.timezone(TIMEZONE)
    now = datetime.datetime.now(tz)
    name = f"🕐 {now.strftime('%I:%M %p')}"
    await channel.edit(name=name)
    e = success_embed(
        "Live Clock Started",
        f"Live clock is now active in {channel.mention}.\nUpdates every **85 seconds**.\nUse `{PREFIX}stopclock` to stop.",
    )
    await ctx.send(embed=e)


@bot.command(name="stopclock")
@commands.has_permissions(manage_channels=True)
async def stopclock(ctx):
    clock_channels.pop(ctx.guild.id, None)
    await ctx.send(embed=success_embed("Live Clock Stopped", "The live clock has been stopped."))


@tasks.loop(seconds=85)
async def update_clock():
    tz = pytz.timezone(TIMEZONE)
    now = datetime.datetime.now(tz)
    name = f"🕐 {now.strftime('%I:%M %p')}"
    for guild_id, channel_id in list(clock_channels.items()):
        guild = bot.get_guild(guild_id)
        if guild:
            channel = guild.get_channel(channel_id)
            if channel:
                try:
                    await channel.edit(name=name)
                except Exception:
                    pass


@bot.command(name="remind")
async def remind(ctx, duration: str, *, message: str):
    seconds = parse_duration(duration)
    remind_at = datetime.datetime.utcnow() + datetime.timedelta(seconds=seconds)
    reminders.append({
        "user_id":    ctx.author.id,
        "channel_id": ctx.channel.id,
        "message":    message,
        "remind_at":  remind_at.isoformat(),
    })
    e = success_embed(
        "Reminder Set ⏰",
        f"I'll remind you in **{duration}**!\n\n📝 **Note:** {message}",
        footer=f"Reminder set by {ctx.author}"
    )
    await ctx.send(embed=e)


@bot.command(name="reminders")
async def list_reminders(ctx):
    user_rems = [r for r in reminders if r["user_id"] == ctx.author.id]
    if not user_rems:
        await ctx.send(embed=info_embed("⏰  Your Reminders", "You have no active reminders."))
        return
    desc = "\n".join(
        f"`{i+1}.` {r['message']} — <t:{int(datetime.datetime.fromisoformat(r['remind_at']).timestamp())}:R>"
        for i, r in enumerate(user_rems)
    )
    await ctx.send(embed=info_embed("⏰  Your Reminders", desc, color=COLOR_CYAN))


@tasks.loop(seconds=10)
async def check_reminders():
    now = datetime.datetime.utcnow()
    to_remove = []
    for rem in reminders:
        if datetime.datetime.fromisoformat(rem["remind_at"]) <= now:
            channel = bot.get_channel(rem["channel_id"])
            if channel:
                user = bot.get_user(rem["user_id"])
                e = discord.Embed(
                    title="⏰  Reminder!",
                    description=f"Hey {user.mention if user else 'there'}!\n\n📝 {rem['message']}",
                    color=COLOR_GOLD
                )
                e.set_footer(text="ModBot Reminder")
                e.timestamp = datetime.datetime.utcnow()
                await channel.send(embed=e)
            to_remove.append(rem)
    for rem in to_remove:
        reminders.remove(rem)


@bot.command(name="dm")
@commands.has_permissions(manage_messages=True)
async def dm_user(ctx, member: discord.Member, *, message: str):
    try:
        e = discord.Embed(
            title=f"📩  Message from {ctx.guild.name}",
            description=message,
            color=COLOR_PURPLE
        )
        e.set_footer(text=f"Sent by {ctx.author} via ModBot")
        e.timestamp = datetime.datetime.utcnow()
        await member.send(embed=e)
        await ctx.send(embed=success_embed("DM Sent", f"Message delivered to **{member}** 📬"))
    except discord.Forbidden:
        await ctx.send(embed=error_embed("DM Failed", f"**{member}** has DMs disabled."))


@bot.command(name="invite")
async def invite(ctx):
    link = f"https://discord.com/api/oauth2/authorize?client_id={bot.user.id}&permissions=8&scope=bot%20applications.commands"
    e = discord.Embed(
        title="📨  Invite ModBot",
        description=f"Click the link below to add **ModBot** to your server!\n\n🔗 **[Click Here to Invite]({link})**",
        color=COLOR_PURPLE
    )
    e.set_footer(text="ModBot™ • Thank you for using ModBot!")
    e.timestamp = datetime.datetime.utcnow()
    if bot.user.avatar:
        e.set_thumbnail(url=bot.user.avatar.url)
    await ctx.send(embed=e)


@bot.command(name="ping")
async def ping(ctx):
    latency = round(bot.latency * 1000)
    color = COLOR_SUCCESS if latency < 100 else COLOR_WARN if latency < 200 else COLOR_ERROR
    e = discord.Embed(
        title="🏓  Pong!",
        description=f"**Latency:** `{latency}ms`",
        color=color
    )
    e.set_footer(text="ModBot")
    await ctx.send(embed=e)


@bot.command(name="serverinfo")
async def serverinfo(ctx):
    g = ctx.guild
    e = discord.Embed(title=f"🏰  {g.name}", color=COLOR_INFO)
    e.add_field(name="👑 Owner",       value=g.owner.mention,           inline=True)
    e.add_field(name="👥 Members",     value=f"{g.member_count:,}",      inline=True)
    e.add_field(name="💬 Channels",    value=str(len(g.channels)),       inline=True)
    e.add_field(name="🎭 Roles",       value=str(len(g.roles)),          inline=True)
    e.add_field(name="😀 Emojis",      value=str(len(g.emojis)),         inline=True)
    e.add_field(name="📅 Created",     value=g.created_at.strftime("%b %d, %Y"), inline=True)
    e.add_field(name="🆔 Server ID",   value=str(g.id),                  inline=True)
    e.add_field(name="🔒 Verification",value=str(g.verification_level).title(), inline=True)
    if g.icon:
        e.set_thumbnail(url=g.icon.url)
    e.set_footer(text="ModBot™")
    e.timestamp = datetime.datetime.utcnow()
    await ctx.send(embed=e)


@bot.command(name="userinfo")
async def userinfo(ctx, member: discord.Member = None):
    member = member or ctx.author
    roles = [r.mention for r in member.roles if r != ctx.guild.default_role]
    e = discord.Embed(
        title=f"👤  {member}",
        color=member.color if member.color.value else COLOR_INFO
    )
    e.add_field(name="🆔 User ID",      value=str(member.id),                        inline=True)
    e.add_field(name="📛 Nickname",     value=member.nick or "None",                  inline=True)
    e.add_field(name="🤖 Bot",          value="Yes" if member.bot else "No",          inline=True)
    e.add_field(name="📅 Joined Server",value=member.joined_at.strftime("%b %d, %Y") if member.joined_at else "N/A", inline=True)
    e.add_field(name="📅 Registered",   value=member.created_at.strftime("%b %d, %Y"),inline=True)
    e.add_field(name=f"🎭 Roles [{len(roles)}]", value=" ".join(roles) if roles else "None", inline=False)
    e.set_thumbnail(url=member.display_avatar.url)
    e.set_footer(text="ModBot™")
    e.timestamp = datetime.datetime.utcnow()
    await ctx.send(embed=e)


@bot.command(name="avatar")
async def avatar(ctx, member: discord.Member = None):
    member = member or ctx.author
    e = discord.Embed(title=f"🖼️  {member}'s Avatar", color=COLOR_CYAN)
    e.set_image(url=member.display_avatar.url)
    e.set_footer(text="ModBot™")
    await ctx.send(embed=e)

# ══════════════════════════════════════════════════════════════════════════════
# AUTO-RESPONDER COMMANDS
# ══════════════════════════════════════════════════════════════════════════════

@bot.command(name="ar")
@commands.has_permissions(manage_messages=True)
async def ar_add(ctx, *, args: str):
    if "|" not in args:
        await ctx.send(embed=error_embed(
            "Invalid Format",
            f"Use: `{PREFIX}ar <trigger> | <response>`\n\nExample: `{PREFIX}ar hello | Hey there!`"
        ))
        return
    trigger, response = [x.strip() for x in args.split("|", 1)]
    autoresponders.setdefault(ctx.guild.id, {})[trigger] = response
    e = success_embed(
        "Auto-Responder Added 🤖",
        f"**Trigger:** `{trigger}`\n**Response:** {response}",
        footer=f"Added by {ctx.author}"
    )
    await ctx.send(embed=e)


@bot.command(name="arlist")
async def ar_list(ctx):
    guild_ars = autoresponders.get(ctx.guild.id, {})
    if not guild_ars:
        await ctx.send(embed=info_embed("🤖  Auto-Responders", "No auto-responders set."))
        return
    desc = "\n".join(f"`{t}` → {r}" for t, r in guild_ars.items())
    await ctx.send(embed=info_embed("🤖  Auto-Responders", desc, color=COLOR_CYAN))


@bot.command(name="ardel")
@commands.has_permissions(manage_messages=True)
async def ar_del(ctx, *, trigger: str):
    guild_ars = autoresponders.get(ctx.guild.id, {})
    if trigger not in guild_ars:
        await ctx.send(embed=error_embed("Not Found", f"No auto-responder with trigger `{trigger}`."))
        return
    del guild_ars[trigger]
    await ctx.send(embed=success_embed("Auto-Responder Deleted", f"Removed trigger `{trigger}`."))
# member locator
@bot.command(name="mc")
async def member_count(ctx):
    guild = ctx.guild

    total_members = guild.member_count
    bot_count = sum(1 for member in guild.members if member.bot)
    human_count = total_members - bot_count

    embed = discord.Embed(
        title=f"{guild.name} Member Count",
        color=discord.Color.blue()
    )
    embed.add_field(name="Total Members", value=total_members, inline=False)
    embed.add_field(name="Humans", value=human_count, inline=True)
    embed.add_field(name="Bots", value=bot_count, inline=True)

    await ctx.send(embed=embed)

    # addme/
    
start_time = time.time()

# Replace with your bot invite link
BOT_INVITE = "https://discord.com/oauth2/authorize?client_id=YOUR_BOT_ID&permissions=8&scope=bot%20applications.commands"


class BotInfoView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

        self.add_item(
            discord.ui.Button(
                label="Add Me",
                url=BOT_INVITE,
                style=discord.ButtonStyle.link
            )
        )


@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # If someone only pings the bot
    if message.content.strip() == f"<@{bot.user.id}>" or message.content.strip() == f"<@!{bot.user.id}>":
        uptime_seconds = int(time.time() - start_time)

        hours = uptime_seconds // 3600
        minutes = (uptime_seconds % 3600) // 60
        seconds = uptime_seconds % 60

        embed = discord.Embed(
            title="Bot Information",
            color=discord.Color.blue()
        )

        embed.description = (
            f"👋 Hello! I'm **{bot.user.name}**\n\n"
            f"🛠️ Developer: **Shubh Srivastav**\n"
            f"⏳ Uptime: **{hours}h {minutes}m {seconds}s**\n"
            f"🏠 Servers: **{len(bot.guilds)}**\n"
            f"👥 Users: **{sum(g.member_count for g in bot.guilds)}**"
        )

        await message.reply(embed=embed, view=BotInfoView(), mention_author=False)

    await bot.process_commands(message)
# ══════════════════════════════════════════════════════════════════════════════
# RUN
# ══════════════════════════════════════════════════════════════════════════════

bot.run(BOT_TOKEN)
