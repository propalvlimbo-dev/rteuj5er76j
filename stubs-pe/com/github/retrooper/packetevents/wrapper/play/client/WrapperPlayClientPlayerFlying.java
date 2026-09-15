package com.github.retrooper.packetevents.wrapper.play.client;

import com.github.retrooper.packetevents.event.PacketReceiveEvent;
import com.github.retrooper.packetevents.protocol.packettype.PacketType;
import com.github.retrooper.packetevents.protocol.packettype.PacketTypeCommon;
import com.github.retrooper.packetevents.protocol.world.Location;

/** Compile-only стаб, сверен с исходниками packetevents v2.13.0. В jar не попадает. */
public class WrapperPlayClientPlayerFlying {

    public WrapperPlayClientPlayerFlying(PacketReceiveEvent event) {
    }

    public static boolean isFlying(PacketTypeCommon packetType) {
        return packetType == PacketType.Play.Client.PLAYER_FLYING
                || packetType == PacketType.Play.Client.PLAYER_POSITION
                || packetType == PacketType.Play.Client.PLAYER_POSITION_AND_ROTATION
                || packetType == PacketType.Play.Client.PLAYER_ROTATION;
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
