package org.bukkit;

import java.util.Collection;
import java.util.UUID;
import org.bukkit.command.CommandSender;
import org.bukkit.command.ConsoleCommandSender;
import org.bukkit.entity.Player;
import org.bukkit.plugin.PluginManager;
import org.bukkit.scheduler.Scheduler;

/** LOCAL-BUILD STUB. Compile-only, never shaded into the jar. */
public interface Server {
    Player getPlayer(UUID uuid);

    Player getPlayerExact(String name);

    Collection<? extends Player> getOnlinePlayers();

    PluginManager getPluginManager();

    Scheduler getScheduler();

    ConsoleCommandSender getConsoleSender();

    boolean dispatchCommand(CommandSender sender, String commandLine);
}
