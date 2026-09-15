package org.bukkit.entity;

import java.util.Collection;
import java.util.UUID;
import org.bukkit.GameMode;
import org.bukkit.Location;
import org.bukkit.command.CommandSender;
import org.bukkit.potion.PotionEffect;

/** LOCAL-BUILD STUB. Compile-only, never shaded into the jar. */
public interface Player extends CommandSender, LivingEntity {
    UUID getUniqueId();

    String getName();

    boolean isOnline();

    boolean isDead();

    GameMode getGameMode();

    boolean isOnGround();

    boolean isGliding();

    boolean isInsideVehicle();

    boolean isInWater();

    boolean isSprinting();

    boolean getAllowFlight();

    Location getLocation();

    Collection<PotionEffect> getActivePotionEffects();

    int getNoDamageTicks();

    boolean isRiptiding();
}
