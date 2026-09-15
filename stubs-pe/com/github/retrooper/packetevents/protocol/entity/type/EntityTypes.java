package com.github.retrooper.packetevents.protocol.entity.type;

/**
 * Compile-only стаб, имена сверены с исходниками packetevents v2.13.0.
 * В jar не попадает.
 */
public final class EntityTypes {

    public static final EntityType PLAYER = new EntityType("player");
    public static final EntityType CAMEL = new EntityType("camel");

    private EntityTypes() {
    }

    public static boolean isTypeInstanceOf(EntityType type, EntityType parent) {
        return type == parent;
    }
}
