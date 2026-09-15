package com.github.retrooper.packetevents.protocol.attribute;

/** Compile-only стаб. В jar не попадает. */
public class Attribute {

    private final String name;

    public Attribute(String name) {
        this.name = name;
    }

    public String getName() {
        return name;
    }
}
