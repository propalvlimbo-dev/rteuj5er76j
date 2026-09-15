package io.github.retrooper.packetevents.packettype;

/**
 * Compile-only стаб, значения сверены с исходниками packetevents v1.8.4.
 * В jar не попадает.
 */
public final class PacketType {

    private PacketType() {
    }

    public static final class Play {

        private Play() {
        }

        public static final class Client {

            private Client() {
            }

            public static final byte POSITION = -96;
            public static final byte POSITION_LOOK = -95;
            public static final byte LOOK = -94;
            public static final byte FLYING = -93;
            public static final byte USE_ENTITY = -100;
            public static final byte ARM_ANIMATION = -71;
            public static final byte KEEP_ALIVE = -98;
            public static final byte TRANSACTION = -107;
            public static final byte BLOCK_DIG = -87;
            public static final byte ENTITY_ACTION = -86;
            public static final byte BLOCK_PLACE = -68;
        }
    }
}
