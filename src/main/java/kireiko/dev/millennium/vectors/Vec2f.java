// Origin: MX-Project (Unlicense) github.com/kireiko/MX-Project — файл 1:1,
package kireiko.dev.millennium.vectors;

public final class Vec2f {

    private float x, y;

    public Vec2f(float x, float y) {
        this.x = x;
        this.y = y;
    }

    public Vec2f(Number x, Number y) {
        this.x = x.floatValue();
        this.y = y.floatValue();
    }

    public double distance(Vec2f vector2) {
        return Math.sqrt(Math.pow(this.x - vector2.x, 2) + Math.pow(this.y - vector2.y, 2));
    }

    public Vec2f add(Vec2f vector2) {
        return new Vec2f(this.x + vector2.x, this.y + vector2.y);
    }

    public Vec2f subtract(Vec2f vector2) {
        return new Vec2f(this.x - vector2.x, this.y - vector2.y);
    }

    public Vec2f scale(double factor) {
        return new Vec2f(this.x * factor, this.y * factor);
    }

    public boolean compare(Vec2f vector2) {
        return this.x == vector2.x && this.y == vector2.y;
    }

    public float getX() {
        return x;
    }

    public float getY() {
        return y;
    }

    public void setX(float x) {
        this.x = x;
    }

    public void setY(float y) {
        this.y = y;
    }

    @Override
    public boolean equals(Object other) {
        if (this == other) {
            return true;
        }
        if (!(other instanceof Vec2f)) {
            return false;
        }
        Vec2f that = (Vec2f) other;
        return Float.compare(x, that.x) == 0 && Float.compare(y, that.y) == 0;
    }

    @Override
    public int hashCode() {
        return Float.hashCode(x) * 31 + Float.hashCode(y);
    }

    @Override
    public String toString() {
        return "Vec2f(x=" + x + ", y=" + y + ")";
    }
}
