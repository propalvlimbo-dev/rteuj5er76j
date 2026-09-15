package ac.grim.grimac.utils.math;

/**
 * EFC-совместимость: Grim Vector3dm (минимальная поверхность).
 */
public class Vector3dm {

    private double x;
    private double y;
    private double z;

    public Vector3dm() {
        this(0, 0, 0);
    }

    public Vector3dm(double x, double y, double z) {
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

    public double distanceSquared(double x, double y, double z) {
        double dx = this.x - x;
        double dy = this.y - y;
        double dz = this.z - z;
        return dx * dx + dy * dy + dz * dz;
    }

    public double distance(double x, double y, double z) {
        return Math.sqrt(distanceSquared(x, y, z));
    }
}
