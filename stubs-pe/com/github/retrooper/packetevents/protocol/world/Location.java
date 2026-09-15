package com.github.retrooper.packetevents.protocol.world;

/**
 * Compile-only стаб, сигнатуры сверены с исходниками packetevents v2.13.0.
 * В jar не попадает.
 */
public class Location {

    private final double x;
    private final double y;
    private final double z;
    private final float yaw;
    private final float pitch;

    public Location(double x, double y, double z) {
        this(x, y, z, 0, 0);
    }

    public Location(double x, double y, double z, float yaw, float pitch) {
        this.x = x;
        this.y = y;
        this.z = z;
        this.yaw = yaw;
        this.pitch = pitch;
    }

    public double getX() {
        return x;
    }

    public double getY() {
        return y;
    }

    public double getZ() {
        return z;
    }

    public float getYaw() {
        return yaw;
    }

    public float getPitch() {
        return pitch;
    }
}
