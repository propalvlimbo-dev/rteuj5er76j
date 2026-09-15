package com.google.common.collect;

import java.util.ArrayList;
import java.util.List;

/** Compile-only стаб guava (на сервере даёт Bukkit). В jar не попадает. */
public final class Lists {
    private Lists() {
    }

    public static <E> List<E> newArrayList() {
        return new ArrayList<>();
    }
}
