package ac.grim.grimac.utils.collisions.datatypes;

import ac.grim.grimac.utils.math.Vector3dm;
import com.github.retrooper.packetevents.util.Vector3i;

/**
 * EFC-совместимость: Grim SimpleCollisionBox (минимальная поверхность:
 * конструкторы, expand, sort, isIntersected).
 */
public class SimpleCollisionBox {

    public double minX;
    public double minY;
    public double minZ;
    public double maxX;
    public double maxY;
    public double maxZ;

    public SimpleCollisionBox(Vector3i pos) {
        this(pos.x, pos.y, pos.z, pos.x + 1, pos.y + 1, pos.z + 1);
    }

    public SimpleCollisionBox(double x1, double y1, double z1, double x2, double y2, double z2) {
        this.minX = Math.min(x1, x2);
        this.minY = Math.min(y1, y2);
        this.minZ = Math.min(z1, z2);
        this.maxX = Math.max(x1, x2);
        this.maxY = Math.max(y1, y2);
        this.maxZ = Math.max(z1, z2);
    }

    public SimpleCollisionBox(Vector3dm min, Vector3dm max) {
        this(min.getX(), min.getY(), min.getZ(), max.getX(), max.getY(), max.getZ());
    }

    public void expand(double value) {
        this.minX -= value;
        this.minY -= value;
        this.minZ -= value;
        this.maxX += value;
        this.maxY += value;
        this.maxZ += value;
    }

    public SimpleCollisionBox sort() {
        double t;
        if (minX > maxX) { t = minX; minX = maxX; maxX = t; }
        if (minY > maxY) { t = minY; minY = maxY; maxY = t; }
        if (minZ > maxZ) { t = minZ; minZ = maxZ; maxZ = t; }
        return this;
    }

    public boolean isIntersected(SimpleCollisionBox other) {
        return minX < other.maxX && maxX > other.minX
                && minY < other.maxY && maxY > other.minY
                && minZ < other.maxZ && maxZ > other.minZ;
    }
}
