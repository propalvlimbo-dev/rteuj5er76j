package org.bukkit.command;

import java.util.List;

/** LOCAL-BUILD STUB. Compile-only, never shaded into the jar. */
public interface TabCompleter {
    List<String> onTabComplete(CommandSender sender, Command command, String alias, String[] args);
}
