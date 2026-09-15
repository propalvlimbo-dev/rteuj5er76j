package com.github.retrooper.packetevents.protocol.world.states.type;

/**
 * Compile-only стаб, сигнатуры сверены с исходниками packetevents v2.13.0.
 * В jar не попадает.
 */
public class StateType {

    private final String name;
    private final boolean air;

    public StateType(String name, boolean air) {
        this.name = name;
        this.air = air;
    }

    public String getName() {
        return name;
    }

    public float getBlastResistance() {
        return 0;
    }

    public float getHardness() {
        return 0;
    }

    public boolean isSolid() {
        return !air;
    }

    public boolean isBlocking() {
        return false;
    }

    public boolean isAir() {
        return air;
    }

    public boolean isRequiresCorrectTool() {
        return false;
    }

    public boolean isReplaceable() {
        return air;
    }

    public boolean exceedsCube() {
        return false;
    }

    @Override
    public String toString() {
        return name;
    }
}
