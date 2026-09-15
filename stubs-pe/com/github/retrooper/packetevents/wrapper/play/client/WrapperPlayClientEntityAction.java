package com.github.retrooper.packetevents.wrapper.play.client;

import com.github.retrooper.packetevents.event.PacketReceiveEvent;

/**
 * Compile-only стаб, имена сверены с исходниками packetevents v2.13.0.
 * В jar не попадает.
 */
public class WrapperPlayClientEntityAction {

    public WrapperPlayClientEntityAction(PacketReceiveEvent event) {
    }

    public Action getAction() {
        return null;
    }

    public enum Action {
        START_SNEAKING,
        STOP_SNEAKING,
        LEAVE_BED,
        START_SPRINTING,
        STOP_SPRINTING,
        START_JUMPING_WITH_HORSE,
        STOP_JUMPING_WITH_HORSE,
        OPEN_HORSE_INVENTORY,
        START_FLYING_WITH_ELYTRA
    }
}
