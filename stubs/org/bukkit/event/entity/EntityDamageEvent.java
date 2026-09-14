package org.bukkit.event.entity;

import org.bukkit.entity.Entity;
import org.bukkit.event.Event;

/** LOCAL-BUILD STUB. Compile-only, never shaded into the jar. */
public class EntityDamageEvent extends Event {
    public Entity getEntity() {
        return null;
    }

    public double getDamage() {
        return 0;
    }

    public DamageCause getCause() {
        return null;
    }

    public boolean isCancelled() {
        return false;
    }

    public void setCancelled(boolean cancel) {
    }
}
