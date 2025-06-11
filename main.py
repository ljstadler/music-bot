import asyncio
import logging
import re
from os import getenv

import discord
import lavalink

url_rx = re.compile(r"https?://(?:www\.)?.+")


class LavalinkVoiceClient(discord.VoiceProtocol):
    def __init__(self, client: discord.Client, channel: discord.abc.Connectable):
        self.client = client
        self.channel = channel
        self.guild_id = channel.guild.id
        self._destroyed = False
        self.lavalink: lavalink.Client[lavalink.DefaultPlayer] = self.client.lavalink

    async def on_voice_server_update(self, data):
        lavalink_data = {"t": "VOICE_SERVER_UPDATE", "d": data}
        await self.lavalink.voice_update_handler(lavalink_data)

    async def on_voice_state_update(self, data):
        channel_id = data["channel_id"]
        if not channel_id:
            await self._destroy()
            return
        self.channel = self.client.get_channel(int(channel_id))
        lavalink_data = {"t": "VOICE_STATE_UPDATE", "d": data}
        await self.lavalink.voice_update_handler(lavalink_data)

    async def connect(
        self,
        *,
        timeout: float,
        reconnect: bool,
        self_deaf: bool = False,
        self_mute: bool = False,
    ) -> None:
        self.lavalink.player_manager.create(guild_id=self.channel.guild.id)
        await self.channel.guild.change_voice_state(
            channel=self.channel, self_mute=self_mute, self_deaf=self_deaf
        )

    async def disconnect(self, *, force: bool = False) -> None:
        player = self.lavalink.player_manager.get(self.channel.guild.id)
        if not force and not player.is_connected:
            return
        await self.channel.guild.change_voice_state(channel=None)
        player.channel_id = None
        await self._destroy()

    async def _destroy(self) -> None:
        self.cleanup()
        if self._destroyed:
            return
        self._destroyed = True
        try:
            await self.lavalink.player_manager.destroy(self.guild_id)
        except lavalink.ClientError:
            pass


class Client(discord.Client):
    def __init__(self):
        intents: discord.Intents = discord.Intents.default()
        intents.message_content = True
        intents.voice_states = True

        discord.utils.setup_logging(level=logging.INFO)
        super().__init__(intents=intents)
        self.tree = discord.app_commands.CommandTree(self)

    async def setup_hook(self):
        self.lavalink = lavalink.Client(self.user.id)
        self.lavalink.add_node(
            host=getenv("LAVALINK_HOST"),
            port=getenv("LAVALINK_PORT"),
            password=getenv("LAVALINK_PASSWORD"),
            region="us",
        )
        self.lavalink.add_event_hooks(self)

    async def on_ready(self):
        logging.info(f"Logged in: {self.user} | {self.user.id}")
        await self.tree.sync()
        await self.change_presence(
            activity=discord.Activity(type=discord.ActivityType.listening, name="Music")
        )

    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        if (
            member.guild.voice_client is not None
            and len(member.guild.voice_client.channel.members) == 1
            and member.guild.voice_client.channel.members[0].id == self.user.id
        ):
            player = self.lavalink.player_manager.get(member.guild.id)
            if not player:
                return
            player.queue.clear()
            await player.stop()
            await member.guild.voice_client.disconnect(force=True)

    @lavalink.listener(lavalink.TrackStartEvent)
    async def on_lavalink_track_start(self, event: lavalink.TrackStartEvent):
        player = event.player
        home = player.fetch("home")
        track = event.track
        embed = discord.Embed(title="Now Playing")
        embed.description = f"**{track.title}** by `{track.author}`"
        embed.url = track.uri
        if track.artwork_url:
            embed.set_image(url=track.artwork_url)
        if track.plugin_info.get("albumName"):
            embed.add_field(name="Album", value=track.plugin_info.get("albumName"))
        await home.send(embed=embed)

    @lavalink.listener(lavalink.QueueEndEvent)
    async def on_lavalink_queue_end(self, event: lavalink.QueueEndEvent):
        player = event.player
        guild_id = player.guild_id
        guild = self.get_guild(guild_id)
        home = player.fetch("home")
        await guild.voice_client.disconnect(force=True)
        await home.send("Disconnected due to queue ending.")

    @lavalink.listener(lavalink.TrackExceptionEvent)
    async def on_lavalink_track_exception(self, event: lavalink.TrackExceptionEvent):
        logging.error(event.message)


client: Client = Client()


@client.tree.command(name="play", description="Play track/s.")
async def play(interaction: discord.Interaction, query: str) -> None:
    await interaction.response.defer()

    player = client.lavalink.player_manager.get(interaction.guild_id)
    if not player:
        player = client.lavalink.player_manager.create(interaction.guild_id)

    voice_client = interaction.guild.voice_client

    if not interaction.user.voice or not interaction.user.voice.channel:
        if voice_client is not None:
            return await interaction.followup.send("Join my voice channel first.")
        return await interaction.followup.send("Join a voice channel first.")

    voice_channel = interaction.user.voice.channel

    if voice_client is None:
        if voice_channel.user_limit > 0:
            if len(voice_channel.members) >= voice_channel.user_limit:
                return await interaction.followup.send("Your voice channel is full.")
        player.store("home", interaction.channel)
        await interaction.user.voice.channel.connect(cls=LavalinkVoiceClient)
    elif voice_client.channel.id != voice_channel.id:
        return await interaction.followup.send("You need to be in my voice channel.")

    query = query.strip("<>")
    if not url_rx.match(query):
        query = f"ytmsearch:{query}"

    results = await player.node.get_tracks(query)
    if results.load_type == lavalink.LoadType.EMPTY:
        return await interaction.followup.send("Could not find any tracks.")
    elif results.load_type == lavalink.LoadType.PLAYLIST:
        tracks = results.tracks
        for track in tracks:
            player.add(track)
        await interaction.followup.send(
            f"Added **`{results.playlist_info.name}`** ({len(tracks)} tracks) to queue."
        )
    else:
        track = results.tracks[0]
        player.add(track)
        await interaction.followup.send(f"Added **`{track.title}`** to queue.")

    if not player.is_playing:
        await player.play()


@client.tree.command(name="pause", description="Pause or resume.")
async def pause(interaction: discord.Interaction) -> None:
    player = client.lavalink.player_manager.get(interaction.guild_id)
    if not player:
        return

    if not player.paused:
        await player.set_pause(True)
        await interaction.response.send_message("Paused.")
    else:
        await player.set_pause(False)
        await interaction.response.send_message("Resumed.")


@client.tree.command(name="seek", description="Seek in current track.")
async def seek(interaction: discord.Interaction, min: int, sec: int) -> None:
    player = client.lavalink.player_manager.get(interaction.guild_id)
    if not player:
        return

    await player.seek((min * 60 * 1000) + (sec * 1000))
    await interaction.response.send_message("Seeked.")


@client.tree.command(name="skip", description="Skip current track.")
async def skip(interaction: discord.Interaction) -> None:
    player = client.lavalink.player_manager.get(interaction.guild_id)
    if not player:
        return

    await player.skip()
    await interaction.response.send_message("Skipped.")


@client.tree.command(name="queue", description="Get queue.")
async def queue(interaction: discord.Interaction) -> None:
    player = client.lavalink.player_manager.get(interaction.guild_id)
    if not player:
        return

    if len(player.queue) > 0:
        clean_queue = []
        for i, track in enumerate(player.queue):
            clean_queue.append(f"{i + 1}: {track.title}")
        clean_queue = "\n".join(clean_queue)
        await interaction.response.send_message(f"Queue:\n```{clean_queue}```")
    else:
        await interaction.response.send_message("Queue is empty.")


@client.tree.command(name="shuffle", description="Shuffle queue.")
async def shuffle(interaction: discord.Interaction) -> None:
    player = client.lavalink.player_manager.get(interaction.guild_id)
    if not player:
        return

    if not player.shuffle:
        player.set_shuffle(True)
        await interaction.response.send_message("Shuffled queue.")
    else:
        player.set_shuffle(False)
        await interaction.response.send_message("Unshuffled queue.")


@client.tree.command(name="remove", description="Remove track from queue.")
async def remove(interaction: discord.Interaction, index: int) -> None:
    player = client.lavalink.player_manager.get(interaction.guild_id)
    if not player:
        return

    track = player.queue[index - 1]
    player.queue.remove(track)
    await interaction.response.send_message("Removed track from queue.")


@client.tree.command(name="stop", description="Stop and clear queue.")
async def stop(interaction: discord.Interaction) -> None:
    player = client.lavalink.player_manager.get(interaction.guild_id)
    if not player:
        return

    player.queue.clear()
    await player.stop()
    await interaction.response.send_message("Stopped.")


@client.tree.command(name="leave", description="Leave voice channel.")
async def leave(interaction: discord.Interaction) -> None:
    player = client.lavalink.player_manager.get(interaction.guild_id)
    if not player:
        return

    player.queue.clear()
    await player.stop()
    await interaction.guild.voice_client.disconnect(force=True)
    await interaction.response.send_message("Left voice channel.")


async def main() -> None:
    async with client:
        await client.start(getenv("TOKEN"))


asyncio.run(main())
