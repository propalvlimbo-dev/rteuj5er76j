// Origin: MX-Project (Unlicense) github.com/kireiko/MX-Project — файл 1:1,
package kireiko.dev.millennium.vectors;

public final class Vec2 {

    private double x, y;

    public Vec2(double x, double y) {
        this.x = x;
        this.y = y;
    }

    public Vec2(Number x, Number y) {
        this.x = x.doubleValue();
        this.y = y.doubleValue();
    }

    public double distance(Vec2 vector2) {
        return Math.sqrt(Math.pow(this.x - vector2.x, 2) + Math.pow(this.y - vector2.y, 2));
    }

    public Vec2 add(Vec2 vector2) {
        return new Vec2(this.x + vector2.x, this.y + vector2.y);
    }

    public Vec2 subtract(Vec2 vector2) {
        return new Vec2(this.x - vector2.x, this.y - vector2.y);
    }

    public Vec2 scale(double factor) {
        return new Vec2(this.x * factor, this.y * factor);
    }

    public boolean compare(Vec2 vector2) {
        return this.x == vector2.x && this.y == vector2.y;
    }

    public double getX() {
        return x;
    }

    public double getY() {
        return y;
    }

    public void setX(double x) {
        this.x = x;
    }

    public void setY(double y) {
        this.y = y;
    }

    @Override
    public boolean equals(Object other) {
        if (this == other) {
            return true;
        }
        if (!(other instanceof Vec2)) {
            return false;
        }
        Vec2 that = (Vec2) other;
        return Double.compare(x, that.x) == 0 && Double.compare(y, that.y) == 0;
    }

    @Override
    public int hashCode() {
        return Double.hashCode(x) * 31 + Double.hashCode(y);
    }

    @Override
    public String toString() {
        return "Vec2(x=" + x + ", y=" + y + ")";
    }
}
