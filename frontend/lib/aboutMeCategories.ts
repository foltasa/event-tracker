// frontend/lib/aboutMeCategories.ts
// Structural descriptors for the About Me per-category form sections.
// Every field maps into the shared taste_facets shape (artists / genres /
// venues / notes). Category-specific labels only affect display.

import type { EventCategory } from "@/lib/types";

export interface CategoryField {
  label: string;
  helper?: string;
  facetField: "artists" | "genres" | "venues" | "notes";
}

export interface CategoryDescriptor {
  key: EventCategory;
  displayName: string;
  fields: CategoryField[];
}

export const SELECTABLE_CATEGORIES: EventCategory[] = [
  "concerts", "party", "comedy", "theater", "arts", "literature",
  "film", "family", "food", "sports", "outdoor",
];

export const CATEGORY_DESCRIPTORS: Record<EventCategory, CategoryDescriptor> = {
  concerts: {
    key: "concerts", displayName: "Concerts",
    fields: [
      { label: "Favourite artists", facetField: "artists", helper: "Comma-separated" },
      { label: "Favourite genres", facetField: "genres", helper: "e.g. punk, indie, jazz" },
      { label: "Favourite venues", facetField: "venues" },
      { label: "Anything else?", facetField: "notes" },
    ],
  },
  party: {
    key: "party", displayName: "Party",
    fields: [
      { label: "Favourite DJs / acts", facetField: "artists" },
      { label: "Favourite genres", facetField: "genres", helper: "e.g. techno, house, drum'n'bass" },
      { label: "Favourite clubs", facetField: "venues" },
      { label: "Anything else?", facetField: "notes" },
    ],
  },
  comedy: {
    key: "comedy", displayName: "Comedy",
    fields: [
      { label: "Favourite comedians", facetField: "artists" },
      { label: "Preferred formats", facetField: "genres", helper: "Stand-up, Kabarett, Improv..." },
      { label: "Favourite venues", facetField: "venues" },
      { label: "Anything else?", facetField: "notes" },
    ],
  },
  theater: {
    key: "theater", displayName: "Theater",
    fields: [
      { label: "Favourite houses", facetField: "venues" },
      { label: "Preferred formats", facetField: "genres", helper: "Musical, Classic, Modern..." },
      { label: "Anything else?", facetField: "notes" },
    ],
  },
  arts: {
    key: "arts", displayName: "Arts",
    fields: [
      { label: "Favourite artists / houses", facetField: "artists" },
      { label: "Preferred formats", facetField: "genres", helper: "Exhibition, Ballet, Contemporary Dance..." },
      { label: "Anything else?", facetField: "notes" },
    ],
  },
  literature: {
    key: "literature", displayName: "Literature",
    fields: [
      { label: "Favourite authors", facetField: "artists" },
      { label: "Preferred formats", facetField: "genres", helper: "Reading, Poetry Slam, Book launch..." },
      { label: "Anything else?", facetField: "notes" },
    ],
  },
  film: {
    key: "film", displayName: "Film",
    fields: [
      { label: "Favourite directors", facetField: "artists" },
      { label: "Genres", facetField: "genres" },
      { label: "Favourite cinemas", facetField: "venues" },
      { label: "Anything else?", facetField: "notes" },
    ],
  },
  family: {
    key: "family", displayName: "Family",
    fields: [
      { label: "Kids' ages", facetField: "genres", helper: "e.g. 3-6, 7-10" },
      { label: "Interests", facetField: "artists" },
      { label: "Anything else?", facetField: "notes" },
    ],
  },
  food: {
    key: "food", displayName: "Food",
    fields: [
      { label: "Favourite cuisines", facetField: "genres" },
      { label: "Preferred formats", facetField: "artists", helper: "Tasting, Festival, Pop-up..." },
      { label: "Anything else?", facetField: "notes" },
    ],
  },
  sports: {
    key: "sports", displayName: "Sports",
    fields: [
      { label: "Sports / disciplines", facetField: "genres" },
      { label: "Favourite teams", facetField: "artists" },
      { label: "Anything else?", facetField: "notes" },
    ],
  },
  outdoor: {
    key: "outdoor", displayName: "Outdoor",
    fields: [
      { label: "Activities", facetField: "genres", helper: "Hiking, Park festival, Nature..." },
      { label: "Anything else?", facetField: "notes" },
    ],
  },
  other: { key: "other", displayName: "Other", fields: [] },
};
