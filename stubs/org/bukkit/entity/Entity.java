package org.bukkit.entity;

import java.util.UUID;
import org.bukkit.Location;

/** LOCAL-BUILD STUB. Compile-only, never shaded into the jar. */
public interface Entity {
    Location getLocation();

    UUID getUniqueId();

    int getEntityId();
}
