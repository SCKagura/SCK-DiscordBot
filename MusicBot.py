import os
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv
import yt_dlp
from collections import deque
import asyncio

# Load environment variables
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# Guild-specific queues
SONG_QUEUES = {}

# Discord bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Called when bot is ready
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"{bot.user} is online!")

# Search using yt_dlp (wrapped async)
async def search_ytdlp_async(query, ydl_opts):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: _extract(query, ydl_opts))

def _extract(query, ydl_opts):
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(query, download=False)

# Playback control commands
@bot.tree.command(name="skip", description="Skips the current playing song")
async def skip(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc and (vc.is_playing() or vc.is_paused()):
        vc.stop()
        await interaction.response.send_message("⏭️ Skipped.")
    else:
        await interaction.response.send_message("❌ Nothing to skip.")

@bot.tree.command(name="pause", description="Pause the currently playing song.")
async def pause(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc and vc.is_playing():
        vc.pause()
        await interaction.response.send_message("⏸️ Paused.")
    else:
        await interaction.response.send_message("❌ Nothing is playing.")

@bot.tree.command(name="resume", description="Resume paused song.")
async def resume(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc and vc.is_paused():
        vc.resume()
        await interaction.response.send_message("▶️ Resumed.")
    else:
        await interaction.response.send_message("❌ Nothing to resume.")

@bot.tree.command(name="stop", description="Stop and clear queue.")
async def stop(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc:
        vc.stop()
        await vc.disconnect()
        SONG_QUEUES[str(interaction.guild.id)] = deque()
        await interaction.response.send_message("⏹️ Stopped and disconnected.")
    else:
        await interaction.response.send_message("❌ Not connected.")

# Main play command
@bot.tree.command(name="play", description="Play a song or add it to the queue.")
@app_commands.describe(song_query="Search or YouTube URL")
async def play(interaction: discord.Interaction, song_query: str):
    await interaction.response.defer()

    try:
        voice_channel = interaction.user.voice.channel
    except AttributeError:
        await interaction.followup.send("❌ You must be in a voice channel.")
        return

    vc = interaction.guild.voice_client
    if vc is None:
        vc = await voice_channel.connect()
    elif vc.channel != voice_channel:
        await vc.move_to(voice_channel)

    ydl_options = {
        "format": "bestaudio[abr<=96]/bestaudio",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "youtube_include_dash_manifest": False,
        "youtube_include_hls_manifest": False,
    }

    is_url = song_query.startswith("http://") or song_query.startswith("https://")
    query = song_query if is_url else f"ytsearch:{song_query}"

    try:
        results = await search_ytdlp_async(query, ydl_options)
    except Exception as e:
        await interaction.followup.send(f"❌ yt_dlp error: {str(e)}")
        return

    if not results:
        await interaction.followup.send("❌ No results found.")
        return

    # Handle search result vs direct URL
    if "entries" in results:
        tracks = results["entries"]
        if not tracks:
            await interaction.followup.send("🔍 No tracks found.")
            return
        first_track = tracks[0]
    else:
        first_track = results

    audio_url = first_track["url"]
    title = first_track.get("title", "Untitled")

    guild_id = str(interaction.guild.id)
    if guild_id not in SONG_QUEUES:
        SONG_QUEUES[guild_id] = deque()

    SONG_QUEUES[guild_id].append((audio_url, title))

    if vc.is_playing() or vc.is_paused():
        await interaction.followup.send(f"➕ Added to queue: **{title}**")
    else:
        await interaction.followup.send(f"🎵 Now playing: **{title}**")
        await play_next_song(vc, guild_id, interaction.channel)

# Play next in queue
async def play_next_song(vc, guild_id, channel):
    if SONG_QUEUES[guild_id]:
        audio_url, title = SONG_QUEUES[guild_id].popleft()
        ffmpeg_options = {
            "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
            "options": "-vn -c:a libopus -b:a 96k",
        }

        # If ffmpeg is in PATH, remove 'executable'
        source = discord.FFmpegOpusAudio(audio_url, **ffmpeg_options, executable="bin\\ffmpeg\\ffmpeg.exe")

        def after_play(error):
            if error:
                print(f"Error playing {title}: {error}")
            fut = play_next_song(vc, guild_id, channel)
            asyncio.run_coroutine_threadsafe(fut, bot.loop)

        vc.play(source, after=after_play)
        await channel.send(f"🎧 Now playing: **{title}**")
    else:
        await vc.disconnect()
        SONG_QUEUES[guild_id] = deque()

# Run bot
bot.run(TOKEN)
