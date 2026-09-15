// Origin: MX-Project (Unlicense) github.com/kireiko/MX-Project — файл 1:1,
package kireiko.dev.millennium.vectors;

public final class Pair<X, Y> {
    private X x;
    private Y y;

    public Pair(X x, Y y) {
        this.x = x;
        this.y = y;
    }

    public X getX() {
        return x;
    }

    public Y getY() {
        return y;
    }

    public void setX(X x) {
        this.x = x;
    }

    public void setY(Y y) {
        this.y = y;
    }

    @Override
    public boolean equals(Object other) {
        if (this == other) {
            return true;
        }
        if (!(other instanceof Pair)) {
            return false;
        }
        Pair<?, ?> that = (Pair<?, ?>) other;
        return (x == null ? that.x == null : x.equals(that.x))
                && (y == null ? that.y == null : y.equals(that.y));
    }

    @Override
    public int hashCode() {
        return (x == null ? 0 : x.hashCode()) * 31 + (y == null ? 0 : y.hashCode());
    }

    @Override
    public String toString() {
        return "Pair(x=" + x + ", y=" + y + ")";
    }
}
