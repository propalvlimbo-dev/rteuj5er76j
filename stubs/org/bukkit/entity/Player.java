package org.bukkit.entity;

import java.util.UUID;
import org.bukkit.GameMode;
import org.bukkit.command.CommandSender;

/** LOCAL-BUILD STUB. Compile-only, never shaded into the jar. */
public interface Player extends CommandSender {
    UUID getUniqueId();

    String getName();

    boolean isOnline();

    boolean isDead();

    GameMode getGameMode();
}
