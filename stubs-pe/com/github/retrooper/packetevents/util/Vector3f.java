package com.github.retrooper.packetevents.util;

/**
 * Compile-only стаб, поля и конструкторы сверены с исходниками packetevents v2.13.0.
 * В jar не попадает.
 */
public class Vector3f {

    public final float x;
    public final float y;
    public final float z;

    public Vector3f() {
        this(0, 0, 0);
    }

    public Vector3f(float x, float y, float z) {
        this.x = x;
        this.y = y;
        this.z = z;
    }

    public float getX() {
        return x;
    }

    public float getY() {
        return y;
    }

    public float getZ() {
        return z;
    }
}
