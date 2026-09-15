package ac.grim.grimac.api.storage.verbose;

/**
 * EFC-совместимость: Grim Verbose. Писатель собирает детали флага строкой.
 */
public class Verbose {

    private final String template;

    private Verbose(String template) {
        this.template = template;
    }

    public static Verbose of(String template) {
        return new Verbose(template);
    }

    public Writer write(VerboseBuf buf) {
        return new Writer();
    }

    public static final class Writer {
        private final StringBuilder detail = new StringBuilder();

        private Writer append(Object value) {
            if (detail.length() > 0) detail.append(' ');
            detail.append(value);
            return this;
        }

        public Writer uint(int value) {
            return append(value);
        }

        public Writer uint(long value) {
            return append(value);
        }

        public Writer uint(float value) {
            return append(value);
        }

        public Writer uint(double value) {
            return append(value);
        }

        public Writer sint(int value) {
            return append(value);
        }

        public Writer sint(long value) {
            return append(value);
        }

        public Writer f64(double value) {
            return append(value);
        }

        public Writer f32(float value) {
            return append(value);
        }

        public Writer f32(double value) {
            return append(value);
        }

        public Writer bool(boolean value) {
            return append(value);
        }

        public Writer mcPos(int x, int y, int z) {
            return append(x + "," + y + "," + z);
        }

        public Writer cursor(float x, float y, float z) {
            return append(x + "," + y + "," + z);
        }

        @Override
        public String toString() {
            return detail.toString();
        }
    }
}
