package com.github.retrooper.packetevents.protocol.potion;

/** Compile-only стаб. В jar не попадает. */
public class PotionType {

    private final String name;

    public PotionType(String name) {
        this.name = name;
    }

    public String getName() {
        return name;
    }
}
