package com.github.retrooper.packetevents.protocol.world.states.type;

/**
 * Compile-only стаб, имена сверены с исходниками packetevents v2.13.0.
 * В jar не попадает.
 */
public final class StateTypes {

    public static final StateType AIR = new StateType("air", true);
    public static final StateType CAVE_AIR = new StateType("cave_air", true);
    public static final StateType VOID_AIR = new StateType("void_air", true);
    public static final StateType WATER = new StateType("water", false);
    public static final StateType LAVA = new StateType("lava", false);
    public static final StateType BUBBLE_COLUMN = new StateType("bubble_column", false);
    public static final StateType SCAFFOLDING = new StateType("scaffolding", false);
    public static final StateType STONE = new StateType("stone", false);
    public static final StateType FIRE = new StateType("fire", false);
    public static final StateType LIGHT = new StateType("light", false);
    public static final StateType MOVING_PISTON = new StateType("moving_piston", false);
    public static final StateType REDSTONE_WIRE = new StateType("redstone_wire", false);
    public static final StateType LECTERN = new StateType("lectern", false);
    public static final StateType CHEST = new StateType("chest", false);

    private StateTypes() {
    }
}
