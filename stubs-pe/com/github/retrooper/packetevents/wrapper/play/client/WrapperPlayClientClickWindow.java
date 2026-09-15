package com.github.retrooper.packetevents.wrapper.play.client;

import com.github.retrooper.packetevents.event.PacketReceiveEvent;

/** Compile-only стаб, сверен с исходниками packetevents v2.13.0. В jar не попадает. */
public class WrapperPlayClientClickWindow {

    public enum WindowClickType {
        PICKUP,
        QUICK_MOVE,
        SWAP,
        CLONE,
        THROW,
        QUICK_CRAFT,
        PICKUP_ALL,
        UNKNOWN
    }

    public WrapperPlayClientClickWindow(PacketReceiveEvent event) {
    }

    public int getWindowId() {
        return 0;
    }

    public int getSlot() {
        return 0;
    }

    public int getButton() {
        return 0;
    }

    public WindowClickType getWindowClickType() {
        return WindowClickType.UNKNOWN;
    }
}
