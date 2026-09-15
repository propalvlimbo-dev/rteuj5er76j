package org.bukkit.entity;

/** LOCAL-BUILD STUB. Compile-only, never shaded into the jar. */
public interface LivingEntity extends Entity {
    org.bukkit.Location getEyeLocation();

    boolean hasPotionEffect(org.bukkit.potion.PotionEffectType type);

    double getEyeHeight();
}
