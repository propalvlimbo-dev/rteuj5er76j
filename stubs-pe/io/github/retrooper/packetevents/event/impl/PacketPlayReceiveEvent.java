package io.github.retrooper.packetevents.event.impl;

import io.github.retrooper.packetevents.packetwrappers.NMSPacket;
import org.bukkit.entity.Player;

/** Compile-only стаб, сверен с исходниками packetevents v1.8.4. В jar не попадает. */
public final class PacketPlayReceiveEvent {

    public Player getPlayer() {
        return null;
    }

    public byte getPacketId() {
        return 0;
    }

    public NMSPacket getNMSPacket() {
        return null;
    }
}
