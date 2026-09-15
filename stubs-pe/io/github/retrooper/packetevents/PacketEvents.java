package io.github.retrooper.packetevents;

import io.github.retrooper.packetevents.event.manager.EventManager;
import io.github.retrooper.packetevents.utils.player.PlayerUtils;

/** Compile-only стаб, сверен с исходниками packetevents v1.8.4. В jar не попадает. */
public final class PacketEvents {

    private PacketEvents() {
    }

    public static PacketEvents get() {
        return null;
    }

    public EventManager getEventManager() {
        return null;
    }

    public PlayerUtils getPlayerUtils() {
        return null;
    }
}
