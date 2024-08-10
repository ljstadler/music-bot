import asyncio
import logging
from typing import cast
from os import getenv

import discord

import wavelink


class Client(discord.Client):
    def __init__(self) -> None:
        intents: discord.Intents = discord.Intents.default()
        intents.message_content = True
        intents.voice_states = True

        discord.utils.setup_logging(level=logging.INFO)
        super().__init__(intents=intents)
        self.tree = discord.app_commands.CommandTree(self)

    async def setup_hook(self) -> None:
        nodes = [
            wavelink.Node(
                uri=getenv("LAVALINK_URI"), password=getenv("LAVALINK_PASSWORD")
            )
        ]

        await wavelink.Pool.connect(nodes=nodes, client=self)

    async def on_ready(self) -> None:
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
    ) -> None:
        if (
            member.guild.voice_client is not None
            and len(member.guild.voice_client.channel.members) == 1
            and member.guild.voice_client.channel.members[0].id == self.user.id
        ):
            await member.guild.voice_client.disconnect()

    async def on_wavelink_node_ready(
        self, payload: wavelink.NodeReadyEventPayload
    ) -> None:
        logging.info(
            f"Wavelink Node connected: {payload.node!r} | Resumed: {payload.resumed}"
        )

    async def on_wavelink_track_start(
        self, payload: wavelink.TrackStartEventPayload
    ) -> None:
        player: wavelink.Player | None = payload.player
        if not player:
            return

        original: wavelink.Playable | None = payload.original
        track: wavelink.Playable = payload.track

        embed: discord.Embed = discord.Embed(title="Now Playing")
        embed.description = f"**{track.title}** by `{track.author}`"
        embed.url = track.uri

        if track.artwork:
            embed.set_image(url=track.artwork)

        if original and original.recommended:
            embed.description += f"\n\n`This track was recommended via {track.source}`"

        if track.album.name:
            embed.add_field(name="Album", value=track.album.name)

        await player.home.send(embed=embed)

    async def on_wavelink_inactive_player(self, player: wavelink.Player) -> None:
        await player.home.send("Disconnected due to inactivity.")
        await player.disconnect()


client: Client = Client()


@client.tree.command(name="play", description="Play a song with the given query.")
async def play(interaction: discord.Interaction, query: str) -> None:
    await interaction.response.defer()

    if not interaction.guild:
        return

    player: wavelink.Player
    player = cast(wavelink.Player, interaction.guild.voice_client)

    if not player:
        try:
            player = await interaction.user.voice.channel.connect(cls=wavelink.Player)
        except AttributeError:
            await interaction.followup.send(
                "Please join a voice channel first before using this command."
            )
            return
        except discord.ClientException:
            await interaction.followup.send(
                "I was unable to join this voice channel. Please try again."
            )
            return

    player.autoplay = wavelink.AutoPlayMode.partial

    if not hasattr(player, "home"):
        player.home = interaction.channel
    elif player.home != interaction.channel:
        await interaction.followup.send(
            f"You can only play songs in {player.home.mention}, as the player has already started there."
        )
        return

    tracks: wavelink.Search = await wavelink.Playable.search(query)
    if not tracks:
        await interaction.followup.send(
            f"{interaction.user.mention} - Could not find any tracks with that query. Please try again."
        )
        return

    if isinstance(tracks, wavelink.Playlist):
        added: int = await player.queue.put_wait(tracks)
        await interaction.followup.send(
            f"Added the playlist **`{tracks.name}`** ({added} songs) to the queue."
        )
    else:
        track: wavelink.Playable = tracks[0]
        await player.queue.put_wait(track)
        await interaction.followup.send(f"Added **`{track}`** to the queue.")

    if not player.playing:
        await player.play(player.queue.get())


@client.tree.command(name="seek", description="Seek to given timestamp.")
async def seek(interaction: discord.Interaction, min: int, sec: int) -> None:
    player: wavelink.Player = cast(wavelink.Player, interaction.guild.voice_client)
    if not player:
        return

    await player.seek((min * 60 * 1000) + (sec * 1000))
    await interaction.response.send_message("Seeked.")


@client.tree.command(name="skip", description="Skip the current song.")
async def skip(interaction: discord.Interaction) -> None:
    player: wavelink.Player = cast(wavelink.Player, interaction.guild.voice_client)
    if not player:
        return

    await player.skip()
    await interaction.response.send_message("Skipped.")


@client.tree.command(name="pause", description="Pause or resume the player.")
async def pause(interaction: discord.Interaction) -> None:
    player: wavelink.Player = cast(wavelink.Player, interaction.guild.voice_client)
    if not player:
        return

    if not player.paused:
        await player.pause(True)
        await interaction.response.send_message("Paused.")
    else:
        await player.pause(False)
        await interaction.response.send_message("Resumed.")


@client.tree.command(name="stop", description="Stop the player and clear its queue.")
async def stop(interaction: discord.Interaction) -> None:
    player: wavelink.Player = cast(wavelink.Player, interaction.guild.voice_client)
    if not player:
        return

    player.queue.reset()
    await player.stop()
    await interaction.response.send_message("Stopped.")


@client.tree.command(name="queue", description="Replies with the player's queue.")
async def queue(interaction: discord.Interaction) -> None:
    player: wavelink.Player = cast(wavelink.Player, interaction.guild.voice_client)
    if not player:
        return

    if player.queue.__len__() > 0:
        clean_queue = []
        for i, track in enumerate(player.queue):
            clean_queue.append(f"{i + 1}: {track.title}")
        clean_queue = "\n".join(clean_queue)
        await interaction.response.send_message(f"Queue:\n```{clean_queue}```")
    else:
        await interaction.response.send_message("Queue is empty.")


@client.tree.command(name="shuffle", description="Shuffle the queue.")
async def shuffle(interaction: discord.Interaction) -> None:
    player: wavelink.Player = cast(wavelink.Player, interaction.guild.voice_client)
    if not player:
        return

    player.queue.shuffle()
    await interaction.response.send_message("Shuffled queue.")


@client.tree.command(name="remove", description="Remove song from queue at index.")
async def remove(interaction: discord.Interaction, index: int) -> None:
    player: wavelink.Player = cast(wavelink.Player, interaction.guild.voice_client)
    if not player:
        return

    track = player.queue.get_at(index - 1)
    player.queue.remove(track)
    await interaction.response.send_message("Removed song from queue.")


@client.tree.command(name="leave", description="Disconnect the player.")
async def leave(interaction: discord.Interaction) -> None:
    player: wavelink.Player = cast(wavelink.Player, interaction.guild.voice_client)
    if not player:
        return

    await player.disconnect()
    await interaction.response.send_message("Left the voice channel.")


async def main() -> None:
    async with client:
        await client.start(getenv("TOKEN"))


asyncio.run(main())
