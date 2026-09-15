package com.github.retrooper.packetevents.protocol.packettype;

/**
 * Compile-only стаб, имена сверены с исходниками packetevents v2.13.0.
 * В jar не попадает.
 */
public final class PacketType {

    private PacketType() {
    }

    public static final class Play {

        private Play() {
        }

        public enum Client implements PacketTypeCommon {
            PLAYER_FLYING,
            PLAYER_POSITION,
            PLAYER_POSITION_AND_ROTATION,
            PLAYER_ROTATION,
            INTERACT_ENTITY,
            ANIMATION,
            PLAYER_DIGGING,
            ENTITY_ACTION,
            PLAYER_BLOCK_PLACEMENT,
            USE_ITEM,
            CREATIVE_INVENTORY_ACTION,
            CLIENT_SETTINGS,
            CLICK_WINDOW,
            TAB_COMPLETE,
            NAME_ITEM
        }
    }
}
