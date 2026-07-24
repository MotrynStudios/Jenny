import discord
from discord.ext import commands
from database import get_main_channel_id, set_main_channel_id


def setup_commands(bot):
    """Setup all Discord commands for the bot"""
    
    @bot.command()
    @commands.has_permissions(administrator=True)
    async def setmainchannel(ctx):
        """Set the current channel as Jenny's main chat channel (admin only)"""
        set_main_channel_id(ctx.channel.id)
        await ctx.send(f"✅ Main channel set to {ctx.channel.mention}!")
    
    @setmainchannel.error
    async def setmainchannel_error(ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("❌ You need Administrator permissions to use this command.")
    
    @bot.command()
    async def getmainchannel(ctx):
        """Show the current main channel"""
        main_channel_id = get_main_channel_id()
        if main_channel_id:
            try:
                channel = bot.get_channel(int(main_channel_id))
                if channel:
                    await ctx.send(f"📍 Main channel is set to: {channel.mention}")
                else:
                    await ctx.send(f"⚠️ Main channel ID is set but channel not found: {main_channel_id}")
            except (ValueError, TypeError) as e:
                await ctx.send(f"⚠️ Invalid main channel ID format: {main_channel_id}")
        else:
            await ctx.send("⚠️ No main channel configured. Use !setmainchannel in the desired channel.")
