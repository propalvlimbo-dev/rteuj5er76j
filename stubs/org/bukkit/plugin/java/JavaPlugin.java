package org.bukkit.plugin.java;

import java.util.logging.Logger;
import org.bukkit.Server;
import org.bukkit.command.PluginCommand;
import org.bukkit.configuration.file.FileConfiguration;
import org.bukkit.plugin.Plugin;
import org.bukkit.plugin.PluginDescriptionFile;

/** LOCAL-BUILD STUB. Compile-only, never shaded into the jar. */
public abstract class JavaPlugin implements Plugin {
    public void onEnable() {
    }

    public void onDisable() {
    }

    public Server getServer() {
        return null;
    }

    public PluginCommand getCommand(String name) {
        return null;
    }

    public Logger getLogger() {
        return null;
    }

    public FileConfiguration getConfig() {
        return null;
    }

    public void reloadConfig() {
    }

    public void saveDefaultConfig() {
    }

    public PluginDescriptionFile getDescription() {
        return null;
    }
}
