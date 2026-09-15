package com.github.retrooper.packetevents.util;

/**
 * Compile-only стаб, сигнатуры сверены с исходниками packetevents v2.13.0.
 * В jar не попадает.
 */
public class Vector3d {

    public double x;
    public double y;
    public double z;

    public Vector3d() {
        this(0, 0, 0);
    }

    public Vector3d(double x, double y, double z) {
        this.x = x;
        this.y = y;
        this.z = z;
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

    public Vector3d add(double x, double y, double z) {
        return new Vector3d(this.x + x, this.y + y, this.z + z);
    }

    public Vector3d add(Vector3d other) {
        return add(other.x, other.y, other.z);
    }

    public Vector3d subtract(double x, double y, double z) {
        return new Vector3d(this.x - x, this.y - y, this.z - z);
    }

    public Vector3d subtract(Vector3d other) {
        return subtract(other.x, other.y, other.z);
    }

    public Vector3d multiply(double x, double y, double z) {
        return new Vector3d(this.x * x, this.y * y, this.z * z);
    }

    public Vector3d multiply(Vector3d other) {
        return multiply(other.x, other.y, other.z);
    }

    public Vector3d multiply(double value) {
        return multiply(value, value, value);
    }

    public Vector3d crossProduct(Vector3d other) {
        return new Vector3d(
                y * other.z - z * other.y,
                z * other.x - x * other.z,
                x * other.y - y * other.x);
    }

    public double dot(Vector3d other) {
        return x * other.x + y * other.y + z * other.z;
    }

    public double distanceSquared(Vector3d other) {
        double dx = x - other.x;
        double dy = y - other.y;
        double dz = z - other.z;
        return dx * dx + dy * dy + dz * dz;
    }
}
