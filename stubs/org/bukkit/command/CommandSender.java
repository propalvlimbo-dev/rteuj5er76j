package org.bukkit.command;

/** LOCAL-BUILD STUB. Compile-only, never shaded into the jar. */
public interface CommandSender {
    void sendMessage(String message);

    boolean hasPermission(String permission);
}
