package com.github.retrooper.packetevents.wrapper.play.client;

import com.github.retrooper.packetevents.event.PacketReceiveEvent;

/** Compile-only стаб, методы подтверждены Grim CrashE + PE 2.13.0. В jar не попадает. */
public class WrapperPlayClientSettings {

    public WrapperPlayClientSettings(PacketReceiveEvent event) {
    }

    public int getViewDistance() {
        return 0;
    }

    public void setViewDistance(int viewDistance) {
    }
}
