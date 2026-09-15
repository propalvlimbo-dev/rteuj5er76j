package org.bukkit;

/** LOCAL-BUILD STUB. Compile-only, never shaded into the jar. */
public enum Material {
    AIR,
    STONE,
    LADDER,
    VINE,
    TWISTING_VINES,
    WEEPING_VINES,
    SCAFFOLDING,
    WATER,
    LAVA,
    COBWEB,
    BOW,
    ICE,
    PACKED_ICE,
    BLUE_ICE,
    SLIME_BLOCK,
    SOUL_SAND,
    SOUL_SOIL,
    HONEY_BLOCK,
    CAVE_AIR,
    VOID_AIR;

    public boolean isEdible() {
        return false;
    }

    public boolean isSolid() {
        return false;
    }
}
