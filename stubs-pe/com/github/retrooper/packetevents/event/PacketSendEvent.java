package com.github.retrooper.packetevents.event;

import com.github.retrooper.packetevents.protocol.packettype.PacketTypeCommon;

/** Compile-only стаб, сверен с исходниками packetevents v2.13.0. В jar не попадает. */
public class PacketSendEvent {

    public <T> T getPlayer() {
        return null;
    }

    public PacketTypeCommon getPacketType() {
        return null;
    }

    public void setCancelled(boolean cancelled) {
    }

    public boolean isCancelled() {
        return false;
    }
}
