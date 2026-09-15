package com.github.retrooper.packetevents;

import com.github.retrooper.packetevents.event.EventManager;
import com.github.retrooper.packetevents.manager.player.PlayerManager;

/** Compile-only стаб, сверен с исходниками packetevents v2.13.0. В jar не попадает. */
public class PacketEventsAPI<T> {

    public EventManager getEventManager() {
        return null;
    }

    public PlayerManager getPlayerManager() {
        return null;
    }
}
