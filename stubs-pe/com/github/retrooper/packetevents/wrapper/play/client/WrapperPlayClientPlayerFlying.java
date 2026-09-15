package com.github.retrooper.packetevents.wrapper.play.client;

import com.github.retrooper.packetevents.event.PacketReceiveEvent;
import com.github.retrooper.packetevents.protocol.world.Location;

/** Compile-only стаб, сверен с исходниками packetevents v2.13.0. В jar не попадает. */
public class WrapperPlayClientPlayerFlying {

    public WrapperPlayClientPlayerFlying(PacketReceiveEvent event) {
    }

    public Location getLocation() {
        return null;
    }

    public boolean hasPositionChanged() {
        return false;
    }

    public boolean hasRotationChanged() {
        return false;
    }

    public boolean isOnGround() {
        return false;
    }
}
