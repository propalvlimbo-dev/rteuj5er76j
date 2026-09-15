package com.github.retrooper.packetevents.wrapper.play.client;

import com.github.retrooper.packetevents.event.PacketReceiveEvent;

/** Compile-only стаб. В jar не попадает. */
public class WrapperPlayClientSpectateEntity {

    public WrapperPlayClientSpectateEntity(PacketReceiveEvent event) {
    }

    public int getEntityId() {
        return 0;
    }
}
