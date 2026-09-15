package com.github.retrooper.packetevents.util;

/**
 * Compile-only стаб, поля и конструкторы сверены с исходниками packetevents v2.13.0.
 * В jar не попадает.
 */
public class Vector3i {

    public final int x;
    public final int y;
    public final int z;

    public Vector3i() {
        this(0, 0, 0);
    }

    public Vector3i(int x, int y, int z) {
        this.x = x;
        this.y = y;
        this.z = z;
    }

    public int getX() {
        return x;
    }

    public int getY() {
        return y;
    }

    public int getZ() {
        return z;
    }

    @Override
    public boolean equals(Object obj) {
        if (this == obj) return true;
        if (!(obj instanceof Vector3i)) return false;
        Vector3i other = (Vector3i) obj;
        return x == other.x && y == other.y && z == other.z;
    }

    @Override
    public int hashCode() {
        int result = x;
        result = 31 * result + y;
        result = 31 * result + z;
        return result;
    }
}
